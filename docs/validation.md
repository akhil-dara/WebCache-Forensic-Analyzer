# Validation

How the parser's output was verified, and what the verification found.

## Method

A real `WebCacheV01.dat` in a dirty-shutdown state (136.5 MB, 257 tables)
was read from a copy, verified by SHA-256 before and after reading.

1. **Coverage.** Every table the database catalogues was opened and read
   to its last row.
2. **Row counts** were checked table by table against an independent
   implementation of the Extensible Storage Engine (ESE) format.
3. **Every cell** of every table was checked against the same independent
   implementation. Both sides were normalised to the stored value
   (integers as numbers, text by its stored encoding, binary as bytes), so
   a difference in presentation could neither hide nor create a mismatch.
4. **Every remaining difference** was traced to the bytes of the record
   that produced it and settled against the format's own rules.

## Results

| Check | Result |
|---|---|
| Tables read | 257 of 257 |
| Rows read | 11,095 |
| Row counts | 257 of 257 tables agree |
| Cells | 296,886 checked; every cell of all 255 data tables agrees |

The only cells that differ are in the database's own system catalogue
(`MSysObjects` and its shadow copy), in five bookkeeping columns, and in
each case the record's bytes show this tool's reading is the one the format
specifies (below).

## How an empty fixed column is reported

ESE marks a fixed column as NULL in two ways: the column lies beyond the
last fixed column the record contains, or the record's null bitmap has the
column's bit set. When the bit is set, the column's slot still holds bytes:
a filler pattern (`0x2A`, the character `*`, repeated). Those bytes are not
a value. This tool honours the null bit and reports the column as empty.

| Column | Cells with the null bit set | Filler bytes in the slot |
|---|---|---|
| RootFlag | 3,148 | `0x2A` (42) |
| RecordOffset | 746 | `0x2A2A` (10794) |
| KeyMost | 742 | `0x2A2A` (10794) |
| LVChunkMax | 526 | `0x2A2A2A2A` (707406378) |
| LCMapFlags | 294 | `0x2A2A2A2A` (707406378) |

Where a column's null bit is clear, the stored value is reported as it is.

## What counts as a record

ESE stores each record in a B-tree leaf node. A node too short to hold the
four-byte record header carries no record, and this tool does not list one
for it. Such a node is a deleted-record stub: Deleted Records lists it
separately, with the key it still carries.
