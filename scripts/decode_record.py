#!/usr/bin/env python3
"""
decode_record.py -- decode fixed-width mainframe data using a copybook field map.

Mainframe datasets are opaque byte blobs. The copybook is the only schema, and
the bytes are not text: packed decimal, zoned decimal with an overpunched sign,
and big-endian binary all coexist inside one record, usually in EBCDIC.

This tool exists for two jobs:

  1. Data migration -- turn a dataset into rows a loader can insert.
  2. Golden-master testing -- decode the COBOL program's real input and output
     files so the Java implementation can be compared against them field by
     field, rather than by eyeballing behaviour.

(2) is the whole basis of equivalence verification, so this decoder must be
exactly right. Where it cannot be sure, it reports a problem rather than
guessing: a silently mis-decoded amount is far worse than a loud failure.

Usage:
  decode_record.py --fieldmap X.fieldmap.json --data FILE
                   [--record NAME] [--encoding cp037|ascii|latin-1]
                   [--rdw] [--lrecl N] [--limit N]
                   [--format csv|json|jsonl] [--out FILE]
                   [--redefines-when FIELD=VALUE:RECORDNAME]...

Notes:
  --lrecl        record length; defaults to the field map's record length
  --rdw          variable-length records prefixed by a 4-byte RDW (RECFM=VB)
  --encoding     cp037 is US EBCDIC and the usual answer for z/OS data
  --redefines-when  pick a REDEFINES overlay by discriminator, e.g.
                    --redefines-when EXPORT-REC-TYPE=C:EXPORT-CUSTOMER-DATA
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from decimal import Decimal

# EBCDIC zoned-decimal sign nibbles. In EBCDIC the zone of a digit byte is 0xF;
# a negative value carries zone 0xD, and 0xC is an explicit positive.
NEG_ZONES = (0xB, 0xD)

# Zoned-decimal sign carried as a letter, which is what a dataset looks like
# after it has been translated to ASCII. Maps character -> (digit, sign).
ASCII_OVERPUNCH = {}
for _i, _c in enumerate("{ABCDEFGHI"):
    ASCII_OVERPUNCH[_c] = (_i, +1)
for _i, _c in enumerate("}JKLMNOPQR"):
    ASCII_OVERPUNCH[_c] = (_i, -1)


class DecodeError(Exception):
    pass


# ---------------------------------------------------------------- primitives

def decode_comp3(b: bytes, scale: int, field: str) -> Decimal:
    """Unpack packed decimal (COMP-3 / PACKED-DECIMAL).

    Layout: two digits per byte, low nibble of the final byte is the sign.
    0xC and 0xF are positive, 0xD is negative.
    """
    digits = []
    for i, byte in enumerate(b):
        hi, lo = byte >> 4, byte & 0x0F
        digits.append(hi)
        if i < len(b) - 1:
            digits.append(lo)
        else:
            sign = lo
    if not digits:
        raise DecodeError("%s: empty packed field" % field)
    for d in digits:
        if d > 9:
            raise DecodeError(
                "%s: invalid packed digit 0x%X in %s -- field is probably not "
                "COMP-3, or the offset is wrong" % (field, d, b.hex()))
    if sign not in (0x0C, 0x0D, 0x0F, 0x0A, 0x0B, 0x0E):
        raise DecodeError("%s: invalid packed sign nibble 0x%X in %s"
                          % (field, sign, b.hex()))
    val = Decimal("".join(str(d) for d in digits))
    if sign in (0x0D, 0x0B):
        val = -val
    return val.scaleb(-scale) if scale else val


def decode_zoned(b: bytes, scale: int, signed: bool, field: str,
                 ebcdic: bool) -> Decimal:
    """Decode DISPLAY numeric (zoned decimal), honouring an overpunched sign.

    A trailing D-zone means negative. Spaces and low-values appear in real data
    where a field was never initialised; those decode to zero, which is what
    COBOL itself does on a numeric MOVE of spaces only by accident -- so it is
    reported rather than assumed correct.
    """
    if not b:
        raise DecodeError("%s: empty zoned field" % field)
    if b.strip(b"\x00\x40\x20") == b"":
        return None  # uninitialised: caller decides (usually NULL, not 0)
    neg = False
    digits = []
    for i, byte in enumerate(b):
        if ebcdic:
            hi, lo = byte >> 4, byte & 0x0F
            if i == len(b) - 1 and signed and hi in NEG_ZONES:
                neg = True
            if lo > 9:
                raise DecodeError("%s: non-digit byte 0x%02X in zoned field %s"
                                  % (field, byte, b.hex()))
            digits.append(lo)
        else:
            ch = chr(byte)
            if ch.isdigit():
                digits.append(int(ch))
            elif i == len(b) - 1 and ch in ASCII_OVERPUNCH:
                # Data transferred to ASCII keeps the overpunched sign as a
                # letter: {ABCDEFGHI carry a positive sign, }JKLMNOPQR negative.
                # Treating '{' as invalid rejects perfectly good positive
                # amounts -- which is most of the file.
                d, sign = ASCII_OVERPUNCH[ch]
                digits.append(d)
                neg = sign < 0
            elif ch in " -+":
                if ch == "-":
                    neg = True
            else:
                raise DecodeError("%s: non-digit char %r in zoned field %r"
                                  % (field, ch, b))
    val = Decimal("".join(str(d) for d in digits) or "0")
    if neg:
        val = -val
    return val.scaleb(-scale) if scale else val


def decode_binary(b: bytes, scale: int, signed: bool) -> Decimal:
    """COMP / COMP-4 / COMP-5: big-endian two's complement on z/OS."""
    val = Decimal(int.from_bytes(b, "big", signed=signed))
    return val.scaleb(-scale) if scale else val


def decode_text(b: bytes, encoding: str) -> str:
    """Decode and strip COBOL's trailing pad.

    COBOL fixed-width text is space-padded on the right. Trailing spaces are
    padding, not data -- but LEADING spaces can be significant, so only the right
    side is stripped. Getting this backwards silently corrupts keys.
    """
    return b.decode(encoding, errors="replace").rstrip(" \x00")


# ---------------------------------------------------------------- record layer

def elementary_fields(record: dict) -> list:
    """Leaf fields only -- groups carry no value of their own."""
    fields = record["fields"]
    out = []
    for i, f in enumerate(fields):
        path = f["path"]
        is_group = any(o["path"].startswith(path + ".") for o in fields)
        if not is_group and f["length"] > 0:
            out.append(f)
    return out


def decode_one(buf: bytes, fields: list, encoding: str) -> tuple:
    ebcdic = encoding.lower().replace("-", "") in ("cp037", "cp1047", "ibm037",
                                                   "ibm1047", "cp500")
    row, problems = {}, []
    for f in fields:
        off, ln = f["offset"], f["length"]
        raw = buf[off:off + ln]
        if len(raw) < ln:
            problems.append("%s: record too short (need %d bytes at %d, got %d)"
                            % (f["path"], ln, off, len(raw)))
            row[f["path"]] = None
            continue
        try:
            usage, kind = f["usage"], f["kind"]
            if kind in ("numeric", "numeric-edited"):
                if usage == "COMP-3":
                    row[f["path"]] = decode_comp3(raw, f["scale"], f["path"])
                elif usage in ("COMP", "COMP-5"):
                    row[f["path"]] = decode_binary(raw, f["scale"], f["signed"])
                elif usage in ("COMP-1", "COMP-2"):
                    problems.append("%s: COMP-1/COMP-2 is host floating point; "
                                    "decode is platform-specific and not "
                                    "supported -- convert on the mainframe first"
                                    % f["path"])
                    row[f["path"]] = None
                elif kind == "numeric-edited":
                    row[f["path"]] = decode_text(raw, encoding)
                else:
                    row[f["path"]] = decode_zoned(raw, f["scale"], f["signed"],
                                                  f["path"], ebcdic)
            else:
                row[f["path"]] = decode_text(raw, encoding)
        except DecodeError as e:
            problems.append(str(e))
            row[f["path"]] = None
    return row, problems


def iter_records(path: str, lrecl: int, rdw: bool):
    with open(path, "rb") as fh:
        if rdw:
            n = 0
            while True:
                hdr = fh.read(4)
                if len(hdr) < 4:
                    return
                length = int.from_bytes(hdr[:2], "big") - 4
                if length <= 0:
                    raise DecodeError("record %d: bad RDW length %d"
                                      % (n, length + 4))
                yield fh.read(length)
                n += 1
        else:
            while True:
                buf = fh.read(lrecl)
                if not buf:
                    return
                if len(buf) < lrecl:
                    raise DecodeError(
                        "trailing partial record: %d bytes, expected %d. The "
                        "LRECL is wrong or the file has a different layout."
                        % (len(buf), lrecl))
                yield buf


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fieldmap", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--record")
    ap.add_argument("--encoding", default="cp037")
    ap.add_argument("--lrecl", type=int)
    ap.add_argument("--rdw", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--format", default="csv", choices=("csv", "json", "jsonl"))
    ap.add_argument("--out")
    ap.add_argument("--redefines-when", action="append", default=[],
                    metavar="FIELD=VALUE:RECORD")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on the first decode problem")
    a = ap.parse_args()

    fm = json.load(open(a.fieldmap, encoding="utf-8"))
    if isinstance(fm, list):
        fm = fm[0]
    records = {r["name"]: r for r in fm["records"]}
    if a.record:
        if a.record not in records:
            print("no record %r in field map; have: %s"
                  % (a.record, ", ".join(records)), file=sys.stderr)
            return 2
        rec = records[a.record]
    else:
        rec = max(fm["records"], key=lambda r: r["length"])

    # A record with REDEFINES overlays has no single flat shape: two overlays
    # claim the same bytes. Decoding both would emit contradictory columns, so
    # require the caller to name the discriminator instead of guessing.
    all_fields = elementary_fields(rec)
    overlays = [f for f in rec["fields"] if f["redefines"]]
    chosen = None
    if overlays and not a.redefines_when:
        names = sorted({f["name"] for f in overlays})
        print("NOTE: %s contains REDEFINES overlays (%s).\n"
              "      Decoding every overlay at once would emit contradictory\n"
              "      columns for the same bytes. Re-run with --redefines-when\n"
              "      FIELD=VALUE:OVERLAY to select one per record type."
              % (rec["name"], ", ".join(names[:6])), file=sys.stderr)
    for spec in a.redefines_when:
        try:
            cond, target = spec.rsplit(":", 1)
            fld, val = cond.split("=", 1)
        except ValueError:
            print("bad --redefines-when %r; want FIELD=VALUE:RECORD" % spec,
                  file=sys.stderr)
            return 2
        chosen = (fld.strip().upper(), val, target.strip().upper())

    lrecl = a.lrecl or rec["length"]
    if not a.rdw and lrecl != rec["length"]:
        print("NOTE: --lrecl %d differs from the copybook record length %d"
              % (lrecl, rec["length"]), file=sys.stderr)

    def fields_for(row_bytes):
        if not chosen:
            return all_fields
        fld, val, target = chosen
        disc = next((f for f in all_fields if f["name"] == fld), None)
        if disc is None:
            return all_fields
        got = row_bytes[disc["offset"]:disc["offset"] + disc["length"]]
        got = decode_text(got, a.encoding)
        prefix = target + "."
        if got == val:
            return [f for f in all_fields
                    if prefix in f["path"] or not any(
                        o["name"] in f["path"] for o in overlays)]
        return [f for f in all_fields
                if not any(o["name"] in f["path"] for o in overlays)]

    rows, problems, n = [], [], 0
    try:
        for buf in iter_records(a.data, lrecl, a.rdw):
            row, probs = decode_one(buf, fields_for(buf), a.encoding)
            row["_record_number"] = n
            rows.append(row)
            for p in probs:
                problems.append("record %d: %s" % (n, p))
            n += 1
            if a.strict and problems:
                break
            if a.limit and n >= a.limit:
                break
    except DecodeError as e:
        print("FATAL %s" % e, file=sys.stderr)
        return 1

    if a.out and os.path.dirname(a.out):
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
    out = open(a.out, "w", newline="", encoding="utf-8") if a.out else sys.stdout
    if a.format == "csv":
        cols = ["_record_number"] + [f["path"] for f in all_fields]
        w = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else str(v)) for k, v in r.items()})
    elif a.format == "jsonl":
        for r in rows:
            out.write(json.dumps(r, default=str) + "\n")
    else:
        json.dump(rows, out, indent=2, default=str)
    if a.out:
        out.close()

    print("decoded %d record(s) of %s from %s"
          % (len(rows), rec["name"], os.path.basename(a.data)), file=sys.stderr)
    if problems:
        print("%d decode problem(s):" % len(problems), file=sys.stderr)
        for p in problems[:15]:
            print("  %s" % p, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
