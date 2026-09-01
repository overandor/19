"""Tests for memory_shell/.

Three groups matter most:

* **Safety** — a pinned block is never evicted, because freeing bytes a
  live session is reading is how a cache turns into one tenant receiving
  another's state.
* **Isolation** — a shared cache is an information leak unless sharing is
  scoped. These tests carry out the probing attack and assert it yields
  nothing.
* **Measurement** — the memory claims are checked against real byte counts
  and, for the weights, against the kernel's own RSS figure.
"""
import os

import pytest

from memory_shell.blocks import Accounting, Block, content_id, resident_set_bytes
from memory_shell.isolation import (
    AccessDenied,
    IsolationPolicy,
    Scope,
    Tenant,
    Visibility,
)
from memory_shell.shell import MemoryShell
from memory_shell.store import BlockStore, BudgetExceeded
from memory_shell.weights import WeightRegistry, measure_sharing

KIB = 1024
MIB = 1024 * 1024


def payload(tag: str, size: int = 4 * KIB) -> bytes:
    return (tag.encode() * size)[:size]


def alice() -> Tenant:
    return Tenant("alice")


def bob() -> Tenant:
    return Tenant("bob")


# ── blocks ──────────────────────────────────────────────────────────────────

class TestBlocks:
    def test_identical_bytes_get_one_name(self):
        assert content_id(b"abc") == content_id(b"abc")
        assert content_id(b"abc") != content_id(b"abd")

    def test_block_verifies_its_own_contents(self):
        block = Block.of(b"state")
        assert block.verify()

    def test_substituted_payload_is_detected(self):
        block = Block.of(b"state")
        block.payload = b"other"
        assert not block.verify(), (
            "a block serving bytes that do not match its name would hand one "
            "session another's state under a trusted id"
        )

    def test_accounting_reports_only_real_savings(self):
        acc = Accounting(logical_bytes=300, resident_bytes=100)
        assert acc.saved_bytes == 200
        assert acc.dedup_ratio == pytest.approx(3.0)

    def test_no_sharing_means_no_saving(self):
        acc = Accounting(logical_bytes=100, resident_bytes=100)
        assert acc.saved_bytes == 0
        assert acc.dedup_ratio == pytest.approx(1.0)

    def test_hit_rate(self):
        assert Accounting(hits=3, misses=1).hit_rate == pytest.approx(0.75)
        assert Accounting().hit_rate == 0.0


# ── store: dedup, budget, eviction safety ───────────────────────────────────

class TestStore:
    def test_identical_payload_stored_once(self):
        store = BlockStore(MIB)
        a = store.put(alice(), payload("x"))
        b = store.put(alice(), payload("x"))
        assert a.block_id == b.block_id
        assert store.block_count() == 1
        assert store.accounting.resident_bytes == 4 * KIB
        assert store.accounting.logical_bytes == 8 * KIB
        assert store.accounting.saved_bytes == 4 * KIB

    def test_pinned_block_is_never_evicted(self):
        store = BlockStore(8 * KIB)
        keep = store.put(alice(), payload("a"))
        store.pin(keep)
        store.put(alice(), payload("b"))
        store.put(alice(), payload("c"))
        assert store.payload(keep) == payload("a"), (
            "evicting a pinned block is a use-after-free for the session "
            "reading it"
        )

    def test_unpinned_blocks_evict_least_recently_used_first(self):
        store = BlockStore(8 * KIB)
        old = store.put(alice(), payload("a"))
        new = store.put(alice(), payload("b"))
        store.get(alice(), new.block_id)          # make `new` more recent
        store.put(alice(), payload("c"))          # forces one eviction
        assert store.get(alice(), old.block_id) is None
        assert store.get(alice(), new.block_id) is not None

    def test_everything_pinned_refuses_rather_than_evicting(self):
        store = BlockStore(8 * KIB)
        for tag in ("a", "b"):
            store.pin(store.put(alice(), payload(tag)))
        with pytest.raises(BudgetExceeded, match="pinned"):
            store.put(alice(), payload("c"))

    def test_block_larger_than_budget_is_refused(self):
        store = BlockStore(4 * KIB)
        with pytest.raises(BudgetExceeded, match="whole budget"):
            store.put(alice(), payload("a", 8 * KIB))

    def test_unpin_makes_a_block_evictable_again(self):
        store = BlockStore(8 * KIB)
        ref = store.put(alice(), payload("a"))
        store.pin(ref)
        store.unpin(ref)
        store.put(alice(), payload("b"))
        store.put(alice(), payload("c"))
        assert store.accounting.evictions >= 1

    def test_stale_index_entry_does_not_resolve(self):
        store = BlockStore(8 * KIB)
        store.store_result(alice(), "input-a", payload("a"))
        store.store_result(alice(), "input-b", payload("b"))
        store.store_result(alice(), "input-c", payload("c"))
        assert store.lookup(alice(), "input-a") is None

    def test_different_inputs_with_equal_output_share_one_block(self):
        store = BlockStore(MIB)
        store.store_result(alice(), "input-1", payload("same"))
        store.store_result(alice(), "input-2", payload("same"))
        assert store.block_count() == 1
        assert store.lookup(alice(), "input-1") is not None
        assert store.lookup(alice(), "input-2") is not None


# ── isolation: the security properties ──────────────────────────────────────

class TestIsolation:
    def test_tenant_cannot_read_another_tenants_state(self):
        store = BlockStore(MIB)
        ref = store.put(alice(), payload("secret"))
        assert store.get(bob(), ref.block_id) is None

    def test_identical_content_is_stored_twice_across_tenants(self):
        store = BlockStore(MIB)
        store.put(alice(), payload("same"))
        store.put(bob(), payload("same"))
        assert store.block_count() == 2, (
            "deduplicating across a trust boundary is the leak; paying for "
            "the second copy is the point"
        )

    def test_probe_leaves_no_trace_on_the_victims_block(self):
        store = BlockStore(MIB)
        ref = store.put(alice(), payload("secret"))
        victim = store._blocks[(Scope.tenant("alice").key, ref.block_id)]
        hits_before, recency_before = victim.hits, victim.last_used_at

        for _ in range(50):
            assert store.get(bob(), ref.block_id) is None

        assert victim.hits == hits_before
        assert victim.last_used_at == recency_before, (
            "a denied read that still advances the block's recency is a "
            "channel: the victim's eviction order becomes observable"
        )

    def test_probe_by_input_is_also_a_plain_miss(self):
        store = BlockStore(MIB)
        store.store_result(alice(), "secret-doc", payload("secret"))
        assert store.lookup(bob(), "secret-doc") is None

    def test_shared_scope_needs_an_explicit_grant(self):
        store = BlockStore(MIB)
        publisher = alice().granted("shared:public")
        ref = store.put(publisher, payload("prompt"), shareable=True, shared_label="public")
        assert store.get(bob(), ref.block_id) is None
        assert store.get(bob().granted("shared:public"), ref.block_id) is not None

    def test_publishing_without_a_grant_is_denied(self):
        store = BlockStore(MIB)
        with pytest.raises(AccessDenied):
            store.put(alice(), payload("p"), shareable=True, shared_label="public")

    def test_deployment_can_disable_shared_publication_entirely(self):
        store = BlockStore(MIB, IsolationPolicy(allow_shared_publication=False))
        granted = alice().granted("shared:public")
        with pytest.raises(AccessDenied, match="disabled"):
            store.put(granted, payload("p"), shareable=True, shared_label="public")

    def test_private_copy_wins_over_a_shared_one(self):
        store = BlockStore(MIB)
        tenant = alice().granted("shared:public")
        private = store.put(tenant, payload("dup"))
        found = store.get(tenant, private.block_id)
        assert found.scope == Scope.tenant("alice").key

    def test_quota_confines_a_flooder_to_its_own_blocks(self):
        store = BlockStore(64 * KIB)
        flooder = Tenant("flooder", quota_bytes=8 * KIB)
        victim = Tenant("victim")
        kept = store.put(victim, payload("victim-state"))

        for i in range(20):
            store.put(flooder, payload(f"flood-{i}"))

        assert store.get(victim, kept.block_id) is not None, (
            "without a quota a flooder evicts the victim's working set and "
            "reads its occupancy off the resulting slowdown"
        )
        assert store.scope_bytes(Scope.tenant("flooder").key) <= 8 * KIB

    def test_tenant_scope_requires_an_id(self):
        with pytest.raises(ValueError):
            Tenant("")

    def test_granting_does_not_mutate_the_original_tenant(self):
        base = alice()
        granted = base.granted("shared:public")
        assert base.shared_scopes == frozenset()
        assert granted.may_read(Scope.shared("public"))

    def test_visibility_is_part_of_the_scope_identity(self):
        assert Scope.tenant("a") != Scope.shared("a")
        assert Scope.tenant("a").kind is Visibility.PRIVATE


# ── weights ─────────────────────────────────────────────────────────────────

@pytest.fixture
def weights_file(tmp_path):
    path = tmp_path / "weights.bin"
    path.write_bytes(os.urandom(2 * MIB))
    return path


class TestWeights:
    def test_repeated_acquisition_maps_once(self, weights_file):
        registry = WeightRegistry()
        first = registry.acquire(weights_file)
        second = registry.acquire(weights_file)
        assert first is second
        assert registry.resident_bytes == 2 * MIB
        assert registry.naive_bytes == 4 * MIB
        assert registry.saved_bytes == 2 * MIB

    def test_saving_grows_with_worker_count(self, weights_file):
        registry = WeightRegistry()
        for _ in range(8):
            registry.acquire(weights_file)
        assert registry.resident_bytes == 2 * MIB
        assert registry.saved_bytes == 14 * MIB

    def test_mapping_released_only_when_last_holder_leaves(self, weights_file):
        registry = WeightRegistry()
        registry.acquire(weights_file)
        registry.acquire(weights_file)
        registry.release(weights_file)
        assert registry.resident_bytes == 2 * MIB
        registry.release(weights_file)
        assert registry.resident_bytes == 0

    def test_segment_is_a_zero_copy_view(self, weights_file):
        registry = WeightRegistry()
        weights = registry.acquire(weights_file)
        view = weights.segment(0, 128)
        assert isinstance(view, memoryview)
        assert bytes(view) == weights_file.read_bytes()[:128]
        view.release()

    def test_segment_out_of_bounds_is_refused(self, weights_file):
        registry = WeightRegistry()
        weights = registry.acquire(weights_file)
        with pytest.raises(ValueError):
            weights.segment(0, 3 * MIB)

    def test_empty_weights_file_refused(self, tmp_path):
        empty = tmp_path / "empty.bin"
        empty.write_bytes(b"")
        with pytest.raises(ValueError):
            WeightRegistry().acquire(empty)

    @pytest.mark.skipif(
        resident_set_bytes() is None, reason="needs /proc/self/statm"
    )
    def test_kernel_agrees_that_mappings_are_shared(self, weights_file):
        """The accounting says sharing works; this asks the kernel."""
        result = measure_sharing(weights_file, mappings=8)
        assert result["naive_bytes"] == 16 * MIB
        assert result["registry_resident_bytes"] == 2 * MIB
        delta = result["rss_delta_bytes"]
        assert delta is not None
        assert delta < 4 * MIB, (
            f"touching 8 mappings of a 2MiB file grew RSS by {delta} bytes; "
            "expected roughly one copy, so the mappings are not being shared"
        )


# ── shell ───────────────────────────────────────────────────────────────────

class TestShell:
    def test_second_identical_request_is_reused(self):
        shell = MemoryShell(MIB)
        calls = []

        def compute():
            calls.append(1)
            return payload("out")

        with shell.session(alice()) as session:
            first = session.run("prefill", b"prompt", compute)
            second = session.run("prefill", b"prompt", compute)

        assert not first.reused and second.reused
        assert second.output == first.output
        assert len(calls) == 1, "a reused result must not recompute"

    def test_reuse_is_faster_than_the_cold_path(self):
        shell = MemoryShell(MIB)

        def slow():
            total = 0
            for i in range(200_000):
                total += i
            return payload("out")

        with shell.session(alice()) as session:
            cold = session.run("prefill", b"p", slow)
            warm = session.run("prefill", b"p", slow)

        assert warm.cost_seconds < cold.cost_seconds
        assert warm.saved_seconds > 0
        assert cold.saved_seconds == 0.0

    def test_one_tenant_does_not_serve_anothers_cached_result(self):
        shell = MemoryShell(MIB)
        with shell.session(alice()) as session:
            session.run("prefill", b"shared-prompt", lambda: payload("alice"))

        calls = []

        def compute():
            calls.append(1)
            return payload("bob")

        with shell.session(bob()) as session:
            result = session.run("prefill", b"shared-prompt", compute)

        assert not result.reused
        assert result.output == payload("bob")
        assert len(calls) == 1

    def test_run_does_not_pin_by_default(self):
        shell = MemoryShell(MIB)
        with shell.session(alice()) as session:
            session.run("prefill", b"p", lambda: payload("out"))
            assert shell.store.pinned_count() == 0, (
                "a session that pins every result eventually pins the whole "
                "budget and cannot allocate against itself"
            )

    def test_held_state_is_pinned_until_close(self):
        shell = MemoryShell(MIB)
        with shell.session(alice()) as session:
            session.run("prefill", b"p", lambda: payload("out"), hold=True)
            assert shell.store.pinned_count() == 1
            assert session.held_bytes == 4 * KIB
        assert shell.store.pinned_count() == 0

    def test_held_state_survives_pressure_from_the_same_session(self):
        shell = MemoryShell(32 * KIB)
        with shell.session(alice()) as session:
            held = session.run("prefill", b"keep", lambda: payload("keep"), hold=True)
            for i in range(20):
                session.run("prefill", f"other-{i}".encode(), lambda i=i: payload(f"o{i}"))
            again = session.run("prefill", b"keep", lambda: payload("nope"))
        assert again.reused
        assert again.output == held.output

    def test_a_long_session_does_not_exhaust_the_budget_against_itself(self):
        shell = MemoryShell(16 * KIB)
        with shell.session(alice()) as session:
            for i in range(100):
                session.run("prefill", f"turn-{i}".encode(), lambda i=i: payload(f"t{i}"))
        assert shell.store.accounting.evictions > 0

    def test_compute_must_return_bytes(self):
        shell = MemoryShell(MIB)
        with shell.session(alice()) as session, pytest.raises(TypeError):
            session.run("prefill", b"p", lambda: "not bytes")

    def test_stats_report_measured_savings(self):
        shell = MemoryShell(MIB)
        with shell.session(alice()) as session:
            for _ in range(4):
                session.run("prefill", b"p", lambda: payload("out"))
        stats = shell.stats()
        assert stats.accounting.saved_bytes == 3 * 4 * KIB
        assert stats.accounting.hit_rate == pytest.approx(0.75)
        assert "saved" in stats.summary()


# ── the loop back to proof_of_avoided_work ──────────────────────────────────

class TestMeteringIntegration:
    def _signer(self):
        import hashlib

        from solders.keypair import Keypair

        return Keypair.from_seed(hashlib.sha256(b"shell").digest())

    def test_a_miss_becomes_a_baseline_sample(self):
        from proof_of_avoided_work.oracle import BaselineOracle

        oracle = BaselineOracle(min_samples=1, min_measurers=1)
        shell = MemoryShell(MIB, signer=self._signer(), oracle=oracle)

        with shell.session(alice()) as session:
            session.run("prefill", b"p", lambda: payload("out"))

        assert len(oracle.samples("prefill")) == 1, (
            "a cache miss is a timed cold execution, which is exactly the "
            "measurement the baseline oracle needs"
        )

    def test_a_hit_becomes_a_signed_claim_with_a_measured_cost(self):
        shell = MemoryShell(MIB, signer=self._signer())

        with shell.session(alice()) as session:
            session.run("prefill", b"p", lambda: payload("out"))
            session.run("prefill", b"p", lambda: payload("out"))

        assert len(shell.claims) == 1
        claim = shell.claims[0]
        assert claim.verify()
        assert claim.actual_cost_seconds > 0
        assert claim.claimed_baseline_seconds is None, (
            "the shell measures rather than asserts; the oracle owns the "
            "baseline"
        )

    def test_claims_reach_settlement_and_survive_audit(self):
        from proof_of_avoided_work.audit import ReexecutionResult
        from proof_of_avoided_work.oracle import BaselineOracle
        from proof_of_avoided_work.settlement import SettlementEngine

        signer = self._signer()
        oracle = BaselineOracle(min_samples=1, min_measurers=1)
        engine = SettlementEngine(oracle=oracle, auditor_pubkey=str(signer.pubkey()))
        shell = MemoryShell(MIB, signer=signer, oracle=oracle, settlement=engine)

        with shell.session(alice()) as session:
            session.run("prefill", b"p", lambda: payload("out"))
            session.run("prefill", b"p", lambda: payload("out"))

        entries = engine.entries()
        assert len(entries) == 1

        served = entries[0].claim.output_digest
        report = engine.run_epoch(
            1,
            b"\x11" * 32,
            1.0,
            lambda c: ReexecutionResult(served, 1.0),
        )
        assert report.fraud_proofs == []
        assert report.settled_claims == 1

    def test_no_signer_means_no_claims(self):
        shell = MemoryShell(MIB)
        with shell.session(alice()) as session:
            session.run("prefill", b"p", lambda: payload("out"))
            session.run("prefill", b"p", lambda: payload("out"))
        assert shell.claims == []


# ── remote front end ────────────────────────────────────────────────────────

class TestRemoteService:
    def _service(self, shell=None, tenant=None, compute=None):
        from memory_shell.remote import RemoteShellService

        return RemoteShellService(
            shell=shell or MemoryShell(MIB),
            tenant=tenant or alice(),
            compute=compute or (lambda wc, p: payload("out")),
        )

    def _call(self, service, request):
        import json

        return json.loads(service.handle(json.dumps(request).encode()))

    def test_ping_reports_the_authenticated_tenant(self):
        response = self._call(self._service(), {"op": "ping"})
        assert response["ok"] and response["tenant"] == "alice"

    def test_client_cannot_name_its_own_tenant(self):
        """The one property the whole front end rests on."""
        service = self._service(tenant=alice())
        response = self._call(
            service, {"op": "ping", "tenant": "bob", "tenant_id": "bob"}
        )
        assert response["tenant"] == "alice", (
            "identity must come from the key sshd authenticated, never from "
            "the request body"
        )

    def test_a_client_cannot_reach_another_tenants_cache(self):
        import base64

        shell = MemoryShell(MIB)
        secret = base64.b64encode(b"secret-doc").decode()

        alice_svc = self._service(shell=shell, tenant=alice(),
                                  compute=lambda wc, p: payload("alice-kv"))
        self._call(alice_svc, {"op": "run", "work_class": "prefill",
                               "payload": secret})

        bob_svc = self._service(shell=shell, tenant=bob(),
                                compute=lambda wc, p: payload("bob-kv"))
        response = self._call(bob_svc, {"op": "run", "work_class": "prefill",
                                        "payload": secret})

        assert response["ok"] and not response["reused"]
        assert base64.b64decode(response["output"]) == payload("bob-kv")

    def test_repeat_request_is_reused(self):
        import base64

        service = self._service()
        request = {"op": "run", "work_class": "prefill",
                   "payload": base64.b64encode(b"prompt").decode()}
        assert not self._call(service, request)["reused"]
        assert self._call(service, request)["reused"]

    def test_unsupported_operation_is_refused_without_echoing_it(self):
        response = self._call(self._service(), {"op": "<script>evil</script>"})
        assert not response["ok"] and response["code"] == "bad_request"
        assert "script" not in response["error"], (
            "echoing an attacker-controlled op into the response lands it in "
            "whatever reads these logs"
        )

    def test_oversized_frame_is_refused(self):
        import json

        from memory_shell.remote import MAX_FRAME_BYTES

        service = self._service()
        response = json.loads(service.handle(b"x" * (MAX_FRAME_BYTES + 1)))
        assert not response["ok"] and response["code"] == "too_large"

    def test_malformed_frames_are_refused(self):
        import json

        service = self._service()
        for frame in (b"{not json", b"[1,2,3]", b'"a string"', b"null"):
            response = json.loads(service.handle(frame))
            assert not response["ok"], frame

    def test_invalid_base64_payload_is_refused(self):
        response = self._call(
            self._service(), {"op": "run", "work_class": "p", "payload": "!!!!"}
        )
        assert not response["ok"] and response["code"] == "bad_request"

    def test_missing_work_class_is_refused(self):
        import base64

        response = self._call(
            self._service(),
            {"op": "run", "payload": base64.b64encode(b"x").decode()},
        )
        assert not response["ok"]

    def test_stat_reports_measured_bytes(self):
        import base64

        service = self._service()
        request = {"op": "run", "work_class": "prefill",
                   "payload": base64.b64encode(b"prompt").decode()}
        self._call(service, request)
        self._call(service, request)

        stats = self._call(service, {"op": "stat"})
        assert stats["ok"]
        assert stats["saved_bytes"] == 4 * KIB
        assert stats["dedup_ratio"] == pytest.approx(2.0)

    def test_serve_loop_answers_each_line(self):
        import base64
        import io
        import json

        from memory_shell.remote import serve

        request = json.dumps(
            {"op": "run", "work_class": "prefill",
             "payload": base64.b64encode(b"prompt").decode()}
        ).encode()
        stdin = io.BytesIO(request + b"\n" + request + b"\n\n")
        stdout = io.BytesIO()

        served = serve(self._service(), stdin, stdout)
        lines = [json.loads(x) for x in stdout.getvalue().splitlines()]

        assert served == 2
        assert [x["reused"] for x in lines] == [False, True]


class TestTenantFromEnvironment:
    def test_refuses_to_serve_without_an_identity(self, monkeypatch):
        from memory_shell.remote import (
            TENANT_ENV_VAR,
            ProtocolError,
            tenant_from_environment,
        )

        monkeypatch.delenv(TENANT_ENV_VAR, raising=False)
        with pytest.raises(ProtocolError, match="refusing to serve"):
            tenant_from_environment()

    def test_blank_identity_is_also_refused(self, monkeypatch):
        from memory_shell.remote import (
            TENANT_ENV_VAR,
            ProtocolError,
            tenant_from_environment,
        )

        monkeypatch.setenv(TENANT_ENV_VAR, "   ")
        with pytest.raises(ProtocolError):
            tenant_from_environment()

    def test_reads_identity_and_grants_from_sshd_environment(self, monkeypatch):
        from memory_shell.remote import (
            SHARED_SCOPES_ENV_VAR,
            TENANT_ENV_VAR,
            tenant_from_environment,
        )

        monkeypatch.setenv(TENANT_ENV_VAR, "alice")
        monkeypatch.setenv(SHARED_SCOPES_ENV_VAR, "shared:public, shared:weights")
        tenant = tenant_from_environment()

        assert tenant.tenant_id == "alice"
        assert tenant.shared_scopes == frozenset({"shared:public", "shared:weights"})
