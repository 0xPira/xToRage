# [WIP] xToRage 😡

`xToRage` is a Python tool that turns a local file into one or more PNG images, then can optionally upload those images through the X Commerce image flow.

## Modes

| Mode | What it does | Capacity per image |
| --- | --- | ---: |
| `stealth` | Encodes data into the least-significant bit of a normal cover image. The user can provide the cover image. | `134,896` bytes |
| `max` | Encodes data into nearly transparent PNG pixels for the largest confirmed payload. | `2,429,896` bytes |

In `stealth` mode, pass your own image with `--cover-image`. If omitted, xToRage uses the bundled placeholder image.

## Install

```bash
pip install -r requirements.txt
```

Optional editable install:

```bash
pip install -e .
```

## Local Usage

Show available modes:

```bash
python -m xtorage.cli modes
```

Check how many images a file needs:

```bash
python -m xtorage.cli plan ./file.bin --mode stealth
python -m xtorage.cli plan ./file.bin --mode max
```

Encode with the default `max` mode:

```bash
python -m xtorage.cli encode ./file.bin --mode max --out-dir ./out/file-bin
```

Encode with `stealth` mode and your own cover image:

```bash
python -m xtorage.cli encode ./file.bin \
  --mode stealth \
  --cover-image ./cover.png \
  --out-dir ./out/file-bin
```

Decode back:

```bash
python -m xtorage.cli decode ./out/file-bin/manifest.json --out ./decoded-file.bin
```

## X Commerce Upload

Prepare an account file based on:

```text
examples/account.example.json
```

Then serve the generated output directory from a public URL and run:

```bash
python -m xtorage.cli upload ./file.bin \
  --mode max \
  --out-dir ./out/file-bin \
  --public-base-url https://example-tunnel.ngrok-free.app/out/file-bin \
  --account ./account.json \
  --output ./upload-result.json
```

Later, retrieve the file from the rehosted Commerce image URLs stored in `upload-result.json`:

```bash
python -m xtorage.cli retrieve ./upload-result.json --out ./retrieved-file.bin
```

For stealth with a cover image:

```bash
python -m xtorage.cli upload ./file.bin \
  --mode stealth \
  --cover-image ./cover.png \
  --out-dir ./out/file-bin \
  --public-base-url https://example-tunnel.ngrok-free.app/out/file-bin \
  --account ./account.json \
  --output ./upload-result.json
```

## Account File

Required fields:

- `owner_id`
- `bearer`
- `cookies.auth_token`
- `cookies.ct0`
- `cookies.twid`


You can also avoid writing account cookies to disk:

```bash
export XTORAGE_ACCOUNT_JSON='[...]'
export XTORAGE_BEARER='<x.com web bearer token>'

python -m xtorage.cli upload ./file.bin \
  --mode max \
  --out-dir ./out/file-bin \
  --public-base-url https://example-tunnel.ngrok-free.app/out/file-bin \
  --account - \
  --output ./upload-result.json
```

## Notes

- `stealth` requires a cover image of at least `600x600`; larger images are center-cropped.
- `max` does not use a cover image.
- Every chunk has integrity metadata. Decode fails if a chunk is corrupted or converted to JPEG.
- `upload-result.json` stores the public rehost URLs needed by `retrieve`; it does not need account cookies for retrieval.
