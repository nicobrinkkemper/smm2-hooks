# SMM2 Level Modification Guide

This guide explains how to decrypt, modify, and re-encrypt Super Mario Maker 2 course files (.bcd).

## Quick Start

```python
from tools.parse_course import decrypt_course
from tools.gen_level import encrypt_course

# Decrypt a level
level = bytearray(decrypt_course('course_data_000.bcd'))

# Modify something (e.g., change name)
new_name = 'MyLevel'.encode('utf-16-le')
level[0xF4:0xF4+len(new_name)] = new_name

# Re-encrypt and save
encrypted = encrypt_course(bytes(level))
with open('course_data_000.bcd', 'wb') as f:
    f.write(encrypted)
```

## BCD File Structure

Total size: **376,832 bytes (0x5C000)**

| Offset | Size | Description |
|--------|------|-------------|
| 0x00-0x0F | 0x10 | Header |
| 0x10-0x5BFCF | 0x5BFC0 | Encrypted course data |
| 0x5BFD0-0x5BFFF | 0x30 | Crypto config |

### Header (0x10 bytes)

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 4 | Version (always 1) |
| 0x04 | 4 | Flags (0x00010010) |
| 0x08 | 4 | CRC32 of decrypted data |
| 0x0C | 4 | Magic "SCDL" |

### Crypto Config (0x30 bytes)

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 0x10 | AES-CBC IV |
| 0x10 | 0x10 | Random state (4 × uint32 for SeadRandom) |
| 0x20 | 0x10 | CMAC of decrypted data |

## Encryption Algorithm

1. Generate 16-byte random state
2. Initialize SeadRandom PRNG with random state
3. Generate **key1** using `create_key(rand, key_table, 16)`
4. Encrypt data with AES-256-CBC using key1 + random IV
5. Generate **key2** (continuing PRNG state from step 3)
6. Compute AES-CMAC of **decrypted** data using key2
7. Build file: header + encrypted + IV + random_state + CMAC

**Critical insight**: The CMAC uses a second key derived by continuing the PRNG state after generating the encryption key.

## Decrypted Course Data Layout

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 1 | Start Y position |
| 0x01 | 1 | Goal Y position |
| 0x02 | 2 | Goal X position |
| 0x04 | 2 | Time limit (seconds) |
| 0x08 | 2 | Year |
| 0x0A | 1 | Month |
| 0x0B | 1 | Day |
| 0x0C | 1 | Hour |
| 0x0D | 1 | Minute |
| 0xF1 | 2 | Style code ("M1", "M3", "MW", "WU", "3W") |
| 0xF4 | 66 | Course name (UTF-16LE) |
| 0x136 | 202 | Description (UTF-16LE) |
| 0x200 | ... | Overworld area data |
| 0x14840 | ... | Subworld area data |

### Style Codes

| Code | Style |
|------|-------|
| M1 | Super Mario Bros. |
| M3 | Super Mario Bros. 3 |
| MW | Super Mario World |
| WU | New Super Mario Bros. U |
| 3W | Super Mario 3D World |

### Themes (byte at area+0x00)

| Value | Theme |
|-------|-------|
| 0 | Ground |
| 1 | Underground |
| 2 | Castle |
| 3 | Airship |
| 4 | Underwater |
| 5 | Ghost House |
| 6 | Snow |
| 7 | Desert |
| 8 | Sky |
| 9 | Forest |

## Runtime Modification

The game re-reads level data from disk when entering Coursebot. You can:

1. Modify the .bcd file while the game is running
2. Exit to Coursebot (without saving if in editor)
3. Re-open the level to see changes

This allows live editing workflows!

## Tools

- `tools/parse_course.py` - Decrypt and parse .bcd files
- `tools/gen_level.py` - Encrypt course data (includes `encrypt_course()`)

## References

- Key tables from [JiXiaomai/SMM2](https://github.com/JiXiaomai/SMM2)
- Level format from [Toost](https://github.com/TheGreatRambler/toost) (level.ksy)
