"""Audit chain: verification, tamper detection (in memory and in the database), redaction, concurrency."""
import asyncio

from sqlalchemy import delete, update

from database.models import AuditLog
from services.shield_store import SqlAuditLog
from shield.audit import GENESIS, InMemoryAuditLog, verify_chain


def filled(n: int = 5) -> InMemoryAuditLog:
    log = InMemoryAuditLog()
    for i in range(n):
        log.append("system", "email_received", {"email_id": f"e{i}", "n": i})
    return log


def test_intact_chain_verifies():
    log = filled()
    r = log.verify()
    assert r.ok and r.checked == 5 and log.records()[0].prev_hash == GENESIS


def test_modified_payload_is_detected():
    recs = filled().records()
    recs[2] = recs[2].model_copy(update={"payload": {"email_id": "e2", "n": 999}})
    r = verify_chain(recs)
    assert not r.ok and r.first_broken_seq == 3 and "modified" in r.reason


def test_modified_actor_is_detected():
    recs = filled().records()
    recs[1] = recs[1].model_copy(update={"actor": "human:attacker"})
    assert verify_chain(recs).first_broken_seq == 2


def test_deleted_record_is_detected():
    recs = filled().records()
    del recs[3]
    r = verify_chain(recs)
    assert not r.ok and r.first_broken_seq == 4


def test_recomputed_hash_breaks_the_next_link():
    from shield.audit import compute_hash

    recs = filled().records()
    r1 = recs[1]
    forged_payload = {"email_id": "e1", "n": -1}
    recs[1] = r1.model_copy(update={"payload": forged_payload,
                                    "hash": compute_hash(r1.prev_hash, r1.seq, r1.ts, r1.actor, r1.event_type, forged_payload)})
    r = verify_chain(recs)
    assert not r.ok and r.first_broken_seq == 3 and "does not link" in r.reason


def test_payload_pii_is_redacted_before_hashing():
    log = InMemoryAuditLog()
    rec = log.append("system", "email_received", {"from": "ravi@example.com", "body": "OTP is 482913"})
    assert rec.payload == {"from": "[EMAIL]", "body": "OTP is [OTP]"} and log.verify().ok


def test_tampering_with_a_database_row_is_detected(with_db):
    async def body(sf):
        log = SqlAuditLog(sf)
        for i in range(6):
            await log.append("system", "verdict", {"email_id": f"e{i}", "label": "SAFE"})
        assert (await log.verify()).ok
        async with sf() as s:
            await s.execute(update(AuditLog).where(AuditLog.seq == 4).values(payload_json={"email_id": "e3", "label": "DANGEROUS"}))
            await s.commit()
        r = await log.verify()
        assert not r.ok and r.first_broken_seq == 4

    with_db(body)


def test_deleting_a_database_row_is_detected(with_db):
    async def body(sf):
        log = SqlAuditLog(sf)
        for i in range(4):
            await log.append("system", "verdict", {"i": i})
        async with sf() as s:
            await s.execute(delete(AuditLog).where(AuditLog.seq == 2))
            await s.commit()
        assert (await log.verify()).first_broken_seq == 2

    with_db(body)


def test_concurrent_appends_keep_one_chain(with_db):
    async def body(sf):
        log = SqlAuditLog(sf)
        await asyncio.gather(*(log.append("system", "e", {"i": i}) for i in range(25)))
        page, total = await log.page(limit=100)
        assert total == 25 and [r.seq for r in page] == list(range(1, 26))
        assert (await log.verify()).ok
        assert await log.head_hash() == page[-1].hash

    with_db(body)


def test_append_retries_when_another_writer_took_the_sequence_number(with_db):
    async def body(sf):
        log = SqlAuditLog(sf)
        await log.append("system", "e", {"i": 0})
        real_head, calls = log.head, []

        async def stale_once(session):
            calls.append(1)
            return None if len(calls) == 1 else await real_head(session)  # first try sees an old head

        log.head = stale_once
        rec = await log.append("system", "e", {"i": 1})
        assert len(calls) == 2 and rec.seq == 2 and (await log.verify()).ok

    with_db(body)


def test_two_writers_on_one_database_do_not_fork_the_chain(with_db):
    async def body(sf):
        a, b = SqlAuditLog(sf), SqlAuditLog(sf)  # separate locks, like two processes
        await asyncio.gather(*(w.append("system", "e", {"i": i}) for i in range(10) for w in (a, b)))
        assert (await a.verify()).ok and (await a.page())[1] == 20

    with_db(body)
