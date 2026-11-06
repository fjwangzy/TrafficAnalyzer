"""Disk-backed lifecycle tombstones and active full-resolution point arrays."""

import json
import sqlite3
from pathlib import Path
from utils_local.runtime_logging import audit_stage


class DiskIdentities:
    def __init__(self, connection, kind):
        self.db, self.kind = connection, kind
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS identities (kind TEXT, id TEXT, PRIMARY KEY(kind,id))"
        )

    def add(self, key):
        self.db.execute(
            "INSERT OR IGNORE INTO identities VALUES (?,?)", (self.kind, str(key))
        )

    def __contains__(self, key):
        return (
            self.db.execute(
                "SELECT 1 FROM identities WHERE kind=? AND id=?", (self.kind, str(key))
            ).fetchone()
            is not None
        )

    def __len__(self):
        return self.db.execute(
            "SELECT count(*) FROM identities WHERE kind=?", (self.kind,)
        ).fetchone()[0]


class DiskArray:
    TAIL_POINTS = 128

    def __init__(self, db, track, field):
        self.db, self.track, self.field, self.count = db, track, field, 0
        self._tail = ()

    def __len__(self):
        return self.count

    def extend(self, values):
        if values:
            record, tail = self.prepare(values, self.count)
            self.db.execute(
                "INSERT INTO arrays VALUES (?,?,?,?,?)",
                record,
            )
            self.accept(len(values), tail)

    def prepare(self, values, start):
        """Encode once; cache the same JSON-normalized values as the disk reader."""
        with audit_stage("egress.point_json_encode_decode"):
            payload = json.dumps(values)
            tail = json.loads(payload)[-self.TAIL_POINTS:]
        return (self.track, self.field, start, len(values), payload), tail

    def accept(self, count, tail):
        # Called only after the SQL write succeeds. Never retain caller objects:
        # freeze each value once here, so every later frame slice is a tuple slice
        # instead of a deep copy plus a plain() walk over every point.
        from services.PipelineEgress import plain

        self._tail = (self._tail + tuple(plain(value) for value in tail))[
            -self.TAIL_POINTS :
        ]
        self.count += count

    def _query(self, sql, parameters):
        with audit_stage("egress.sql_select"):
            cursor = self.db.execute(sql, parameters)
        while True:
            with audit_stage("egress.sql_fetch"):
                row = cursor.fetchone()
            if row is None:
                break
            yield row

    def __iter__(self):
        cursor = self._query(
            "SELECT payload FROM arrays WHERE track=? AND field=? ORDER BY start",
            (self.track, self.field),
        )
        for (payload,) in cursor:
            with audit_stage("egress.sql_json_decode"):
                values = json.loads(payload)
            yield from values

    def __getitem__(self, key):
        """Slice from the frozen tail cache, or fall back to SQLite.

        The cache path returns an immutable tuple; the SQL fallback returns a
        list.  ``restore_fact_tails`` treats a tuple as already-normalised.
        """
        if isinstance(key, int):
            n = key if key >= 0 else self.count + key
            if n < 0 or n >= self.count:
                raise IndexError(key)
            result = self[n : n + 1]
            if not result:
                raise IndexError(key)
            return result[0]
        start, stop, step = key.indices(self.count)
        if step != 1:
            return list(self)[key]
        if stop <= start:
            return []
        tail_start = self.count - len(self._tail)
        if start >= tail_start:
            # Tail values are frozen at accept time (tuples, not lists), so elements
            # can be shared.  Hand out fresh dictionaries so a consumer cannot
            # mutate the cache through the quality lineage dictionaries.
            return tuple(
                dict(value) if type(value) is dict else value
                for value in self._tail[start - tail_start : stop - tail_start]
            )
        result = []
        cursor = self._query(
            "SELECT start,payload FROM arrays WHERE track=? AND field=? AND start<? AND start+size>? ORDER BY start",
            (self.track, self.field, stop, start),
        )
        for offset, payload in cursor:
            with audit_stage("egress.sql_json_decode"):
                values = json.loads(payload)
            result.extend(
                values[max(0, start - offset) : min(len(values), stop - offset)]
            )
        return result


def connection(root, *, cache_kib=16384):
    # Default SQLite's ~2MiB cannot hold the current insertion pages for hundreds
    # of tracks × seven fields. Keep an explicit, bounded page-cache budget;
    # journal/synchronous/cache_spill policies retain SQLite defaults.
    if type(cache_kib) is not int or not 512 <= cache_kib <= 65536:
        raise ValueError("egress SQLite cache budget must be 512..65536 KiB")
    Path(root).mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(Path(root) / "trajectory-state.sqlite3")
    db.execute(f"PRAGMA cache_size=-{cache_kib}")
    db.execute(
        "CREATE TABLE IF NOT EXISTS arrays (track TEXT, field TEXT, start INTEGER, size INTEGER, payload TEXT, PRIMARY KEY(track,field,start))"
    )
    return db


class DiskHashes:
    def __init__(self, root):
        self.db = sqlite3.connect(Path(root) / "packet-checksums.sqlite3")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS hashes (role TEXT, seq INTEGER, checksum TEXT, PRIMARY KEY(role,seq))"
        )

    def __contains__(self, key):
        return (
            self.db.execute(
                "SELECT 1 FROM hashes WHERE role=? AND seq=?", key
            ).fetchone()
            is not None
        )

    def __getitem__(self, key):
        row = self.db.execute(
            "SELECT checksum FROM hashes WHERE role=? AND seq=?", key
        ).fetchone()
        if row is None:
            raise KeyError(key)
        return row[0]

    def __setitem__(self, key, value):
        self.db.execute("INSERT INTO hashes VALUES (?,?,?)", (*key, value))

    def close(self):
        self.db.commit()
        self.db.close()
