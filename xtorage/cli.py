from __future__ import annotations

import argparse
import json
from pathlib import Path

from .codec import MODES, PROFILES, decode_manifest, encode_file, plan_file
from .commerce import retrieve_upload_result, upload_manifest


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def cmd_modes(_args: argparse.Namespace) -> None:
    print_json(
        {
            "profiles": {
                name: {
                    "codec": data["codec"],
                    "description": data["description"],
                    "max_payload_bytes_per_image": MODES[data["codec"]].max_payload_bytes,
                    "visual_note": MODES[data["codec"]].visual_note,
                }
                for name, data in PROFILES.items()
            },
            "advanced_codecs": [
                {
                    "name": spec.name,
                    "width": spec.width,
                    "height": spec.height,
                    "capacity_bytes": spec.capacity_bytes,
                    "max_payload_bytes": spec.max_payload_bytes,
                    "visual_note": spec.visual_note,
                }
                for spec in MODES.values()
            ],
        }
    )


def cmd_plan(args: argparse.Namespace) -> None:
    print_json(plan_file(args.file, args.codec or args.mode, args.payload_size))


def cmd_encode(args: argparse.Namespace) -> None:
    print_json(encode_file(args.file, args.out_dir, args.codec or args.mode, args.payload_size, args.cover_image))


def cmd_decode(args: argparse.Namespace) -> None:
    print_json(decode_manifest(args.manifest, args.out, args.image_dir))


def cmd_commerce_upload(args: argparse.Namespace) -> None:
    print_json(
        upload_manifest(
            account_path=args.account,
            manifest_path=args.manifest,
            public_base_url=args.public_base_url,
            catalog_id=args.catalog_id,
            poll_count=args.poll_count,
            poll_delay=args.poll_delay,
            cleanup=args.cleanup,
            output_path=args.output,
        )
    )


def cmd_upload(args: argparse.Namespace) -> None:
    manifest = encode_file(args.file, args.out_dir, args.codec or args.mode, args.payload_size, args.cover_image)
    result = upload_manifest(
        account_path=args.account,
        manifest_path=Path(manifest["manifest_path"]),
        public_base_url=args.public_base_url,
        catalog_id=args.catalog_id,
        poll_count=args.poll_count,
        poll_delay=args.poll_delay,
        cleanup=args.cleanup,
        output_path=None,
    )
    combined = {"encoded": manifest, "uploaded": result}
    args.output.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print_json(combined)


def cmd_retrieve(args: argparse.Namespace) -> None:
    print_json(retrieve_upload_result(args.upload_result, args.out, args.download_dir))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xtorage")
    sub = parser.add_subparsers(dest="cmd", required=True)

    modes = sub.add_parser("modes", help="list confirmed encoding modes")
    modes.set_defaults(func=cmd_modes)

    plan = sub.add_parser("plan", help="show how many images a file needs")
    plan.add_argument("file", type=Path)
    plan.add_argument("--mode", choices=PROFILES.keys(), default="max")
    plan.add_argument("--codec", choices=MODES.keys(), help="advanced: override the profile with a specific codec")
    plan.add_argument("--payload-size", type=int)
    plan.set_defaults(func=cmd_plan)

    enc = sub.add_parser("encode", help="encode a file into PNG chunks")
    enc.add_argument("file", type=Path)
    enc.add_argument("--out-dir", type=Path, required=True)
    enc.add_argument("--mode", choices=PROFILES.keys(), default="max")
    enc.add_argument("--codec", choices=MODES.keys(), help="advanced: override the profile with a specific codec")
    enc.add_argument("--payload-size", type=int)
    enc.add_argument("--cover-image", type=Path, help="stealth only: base image to carry the LSB payload")
    enc.set_defaults(func=cmd_encode)

    dec = sub.add_parser("decode", help="decode chunks listed in a manifest")
    dec.add_argument("manifest", type=Path)
    dec.add_argument("--out", type=Path)
    dec.add_argument("--image-dir", type=Path)
    dec.set_defaults(func=cmd_decode)

    up = sub.add_parser("commerce-upload", help="upload generated chunks as X Commerce products")
    up.add_argument("manifest", type=Path)
    up.add_argument("--account", type=Path, required=True)
    up.add_argument("--public-base-url", required=True, help="public URL serving the manifest image directory")
    up.add_argument("--catalog-id", help="existing catalog id; omitted creates a new catalog")
    up.add_argument("--poll-count", type=int, default=18)
    up.add_argument("--poll-delay", type=float, default=10.0)
    up.add_argument("--cleanup", action="store_true", help="delete products/catalog after polling")
    up.add_argument("--output", type=Path, default=Path("upload_manifest.json"))
    up.set_defaults(func=cmd_commerce_upload)

    upload = sub.add_parser("upload", help="encode a file and upload all generated chunks")
    upload.add_argument("file", type=Path)
    upload.add_argument("--account", type=Path, required=True)
    upload.add_argument("--out-dir", type=Path, required=True)
    upload.add_argument("--public-base-url", required=True, help="public URL serving --out-dir")
    upload.add_argument("--mode", choices=PROFILES.keys(), default="max")
    upload.add_argument("--codec", choices=MODES.keys(), help="advanced: override the profile with a specific codec")
    upload.add_argument("--payload-size", type=int)
    upload.add_argument("--cover-image", type=Path, help="stealth only: base image to carry the LSB payload")
    upload.add_argument("--catalog-id", help="existing catalog id; omitted creates a new catalog")
    upload.add_argument("--poll-count", type=int, default=18)
    upload.add_argument("--poll-delay", type=float, default=10.0)
    upload.add_argument("--cleanup", action="store_true", help="delete products/catalog after polling")
    upload.add_argument("--output", type=Path, default=Path("upload_manifest.json"))
    upload.set_defaults(func=cmd_upload)

    ret = sub.add_parser("retrieve", help="download Commerce rehosted images from an upload result and decode the file")
    ret.add_argument("upload_result", type=Path)
    ret.add_argument("--out", type=Path)
    ret.add_argument("--download-dir", type=Path)
    ret.set_defaults(func=cmd_retrieve)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
