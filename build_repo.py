#!/usr/bin/env python3
import bz2
import datetime
import gzip
import hashlib
import json
import lzma
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zlib
from pathlib import Path


def fetch_json(url: str, token: str | None = None) -> list | dict:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "Cat-Ling-APT-Repo-Builder")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(url: str, dest: Path) -> None:
    subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "-o", str(dest), url],
        check=True,
    )


def file_hashes(path: Path) -> dict[str, str | int]:
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    sha512 = hashlib.sha512()
    size = 0
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            size += len(chunk)
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
            sha512.update(chunk)
    return {
        "size": size,
        "md5": md5.hexdigest(),
        "sha1": sha1.hexdigest(),
        "sha256": sha256.hexdigest(),
        "sha512": sha512.hexdigest(),
    }


def extract_deb_control(deb_path: Path) -> dict[str, str]:
    raw = subprocess.check_output(["dpkg-deb", "-f", str(deb_path)], text=True)
    fields: dict[str, str] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line[0] in (" ", "\t") and current_key:
            fields[current_key] += "\n" + line
        elif ":" in line:
            key, val = line.split(":", 1)
            current_key = key.strip()
            fields[current_key] = val.strip()
    return fields


def generate_png_icon(dest: Path, size: int = 128) -> None:
    width = height = size
    raw_rows = bytearray()
    for y in range(height):
        raw_rows.append(0)
        for x in range(width):
            nx = (x / (width - 1)) * 2.0 - 1.0
            ny = (y / (height - 1)) * 2.0 - 1.0
            dist = (nx * nx + ny * ny) ** 0.5
            r = int(28 + 90 * (x / width))
            g = int(25 + 40 * (1.0 - y / height))
            b = int(68 + 145 * (y / height))
            if 0.42 <= dist <= 0.62 and nx < 0.25:
                r, g, b = 235, 240, 255
            raw_rows.extend((r, g, b, 255))

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw_rows), 9)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    dest.write_bytes(png)


def build_sileo_depiction(
    pkg_id: str,
    latest_fields: dict[str, str],
    versions: list[dict],
    repo_url: str,
) -> dict:
    pkg_name = latest_fields.get("Name", pkg_id)
    desc = latest_fields.get("Description", "")
    author = latest_fields.get("Author", latest_fields.get("Maintainer", "Cat-Ling"))
    section = latest_fields.get("Section", "Tweaks")

    changelog_views = []
    for v in versions:
        ver_str = v["version"]
        date_str = v["published_at"][:10] if v.get("published_at") else "Release"
        notes = (v.get("release_notes") or "").strip()
        if not notes:
            notes = f"Release {ver_str} ({v['arch']})."
        changelog_views.append(
            {
                "class": "DepictionSubheaderView",
                "title": f"Version {ver_str} ({date_str})",
                "useBoldText": True,
            }
        )
        changelog_views.append(
            {
                "class": "DepictionMarkdownView",
                "markdown": notes,
            }
        )
        changelog_views.append({"class": "DepictionSeparatorView"})

    return {
        "minVersion": "0.4",
        "class": "DepictionTabView",
        "headerImage": f"{repo_url}/banner.png",
        "tintColor": "#6366F1",
        "tabs": [
            {
                "tabname": "Details",
                "class": "DepictionStackView",
                "views": [
                    {
                        "class": "DepictionSubheaderView",
                        "title": pkg_name,
                        "useBoldText": True,
                    },
                    {
                        "class": "DepictionMarkdownView",
                        "markdown": (
                            f"{desc}\n\n"
                            "**Compatibility Note:** Declared firmware boundaries in package metadata do not guarantee compatibility across every iOS version. "
                            "Tested specifically on **iOS 15 rootless (Dopamine, arm64)**."
                        ),
                    },
                    {"class": "DepictionSeparatorView"},
                    {
                        "class": "DepictionTableTextView",
                        "title": "Latest Version",
                        "text": versions[0]["version"],
                    },
                    {
                        "class": "DepictionTableTextView",
                        "title": "Architecture",
                        "text": latest_fields.get("Architecture", "iphoneos-arm64"),
                    },
                    {
                        "class": "DepictionTableTextView",
                        "title": "Section",
                        "text": section,
                    },
                    {
                        "class": "DepictionTableTextView",
                        "title": "Author",
                        "text": author,
                    },
                    {
                        "class": "DepictionTableButtonView",
                        "title": "Source Code on GitHub",
                        "action": f"https://github.com/{versions[0]['source_repo']}",
                    },
                ],
            },
            {
                "tabname": "Changelog",
                "class": "DepictionStackView",
                "views": changelog_views,
            },
        ],
    }


def build_web_depiction(
    pkg_id: str,
    latest_fields: dict[str, str],
    versions: list[dict],
) -> str:
    pkg_name = latest_fields.get("Name", pkg_id)
    desc = latest_fields.get("Description", "")
    history_items = []
    for v in versions:
        date_str = v["published_at"][:10] if v.get("published_at") else ""
        notes = (v.get("release_notes") or f"Release {v['version']}").strip()
        history_items.append(
            f"<div class='ver'><strong>v{v['version']}</strong> <span>({v['arch']} · {date_str})</span>"
            f"<pre>{notes}</pre></div>"
        )
    history_html = "\n".join(history_items)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{pkg_name} - Cat-Ling Repo</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
  .card {{ max-width: 640px; margin: 0 auto 16px; background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
  h1 {{ margin-top: 0; font-size: 1.4rem; }}
  h2 {{ font-size: 1.1rem; color: #94a3b8; margin-top: 0; }}
  .note {{ background: #312e81; border-left: 4px solid #6366f1; padding: 12px; border-radius: 6px; font-size: 0.9rem; margin-top: 12px; }}
  .ver {{ border-top: 1px solid #334155; padding-top: 12px; margin-top: 12px; }}
  .ver span {{ color: #94a3b8; font-size: 0.85rem; }}
  pre {{ white-space: pre-wrap; font-family: inherit; font-size: 0.9rem; color: #cbd5e1; margin: 6px 0 0; }}
  a {{ color: #818cf8; }}
</style>
</head>
<body>
  <div class="card">
    <h1>{pkg_name}</h1>
    <p>{desc}</p>
    <div class="note">
      <strong>Note:</strong> Declared firmware ranges in control metadata do not guarantee compatibility across all iOS versions. Patched and verified for iOS 15 rootless (Dopamine, arm64).
    </div>
  </div>
  <div class="card">
    <h2>Version History</h2>
    {history_html}
  </div>
</body>
</html>
"""


def main() -> int:
    root_dir = Path(__file__).resolve().parent
    config = json.loads((root_dir / "repos.json").read_text(encoding="utf-8"))
    out_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root_dir / "_site"

    if out_dir.exists():
        shutil.rmtree(out_dir)
    debs_dir = out_dir / "debs"
    depictions_dir = out_dir / "depictions"
    web_depictions_dir = depictions_dir / "web"
    debs_dir.mkdir(parents=True, exist_ok=True)
    web_depictions_dir.mkdir(parents=True, exist_ok=True)

    token = os.environ.get("GITHUB_TOKEN")
    repo_url = config["repo_url"].rstrip("/")

    seen_pkg_arch_ver: set[tuple[str, str, str]] = set()
    stanzas: list[str] = []
    packages_by_id: dict[str, dict] = {}

    for source_repo in config["source_repositories"]:
        api_url = f"https://api.github.com/repos/{source_repo}/releases?per_page=30"
        print(f"Fetching releases from {source_repo}...")
        releases = fetch_json(api_url, token)
        if not isinstance(releases, list):
            continue

        for rel in releases:
            if rel.get("draft"):
                continue
            published_at = rel.get("published_at") or rel.get("created_at") or ""
            release_notes = rel.get("body") or ""
            for asset in rel.get("assets", []):
                asset_name = asset.get("name", "")
                if not asset_name.endswith(".deb"):
                    continue
                dl_url = asset.get("browser_download_url")
                if not dl_url:
                    continue

                with tempfile.TemporaryDirectory() as tmpd:
                    tmp_deb = Path(tmpd) / asset_name
                    print(f"  Downloading {asset_name} from {source_repo}@{rel.get('tag_name')}...")
                    download_file(dl_url, tmp_deb)
                    fields = extract_deb_control(tmp_deb)

                    pkg_id = fields.get("Package")
                    version = fields.get("Version")
                    arch = fields.get("Architecture")
                    if not pkg_id or not version or not arch:
                        continue

                    key = (pkg_id, arch, version)
                    if key in seen_pkg_arch_ver:
                        print(f"  Skipping duplicate {pkg_id} {version} ({arch})")
                        continue
                    seen_pkg_arch_ver.add(key)

                    canonical_deb_name = f"{pkg_id}_{version}_{arch}.deb"
                    final_deb_path = debs_dir / canonical_deb_name
                    shutil.copy2(tmp_deb, final_deb_path)
                    hashes = file_hashes(final_deb_path)

                    fields["Homepage"] = f"https://github.com/{source_repo}"
                    fields["Depiction"] = f"{repo_url}/depictions/web/{pkg_id}.html"
                    fields["SileoDepiction"] = f"{repo_url}/depictions/{pkg_id}.json"

                    ordered_keys = [
                        "Package",
                        "Name",
                        "Version",
                        "Architecture",
                        "Priority",
                        "Section",
                        "Maintainer",
                        "Author",
                        "Pre-Depends",
                        "Depends",
                        "Conflicts",
                        "Provides",
                        "Replaces",
                        "Installed-Size",
                        "Homepage",
                        "Depiction",
                        "SileoDepiction",
                        "Tag",
                        "Description",
                    ]
                    lines = []
                    used = set()
                    for k in ordered_keys:
                        if k in fields:
                            lines.append(f"{k}: {fields[k]}")
                            used.add(k)
                    for k, v in fields.items():
                        if k not in used:
                            lines.append(f"{k}: {v}")

                    lines.append(f"Filename: debs/{canonical_deb_name}")
                    lines.append(f"Size: {hashes['size']}")
                    lines.append(f"MD5sum: {hashes['md5']}")
                    lines.append(f"SHA1: {hashes['sha1']}")
                    lines.append(f"SHA256: {hashes['sha256']}")
                    lines.append(f"SHA512: {hashes['sha512']}")
                    stanzas.append("\n".join(lines) + "\n")

                    if pkg_id not in packages_by_id:
                        packages_by_id[pkg_id] = {
                            "latest_fields": fields,
                            "versions": [],
                        }
                    packages_by_id[pkg_id]["versions"].append(
                        {
                            "version": version,
                            "arch": arch,
                            "published_at": published_at,
                            "release_notes": release_notes,
                            "source_repo": source_repo,
                            "deb_name": canonical_deb_name,
                            "size": hashes["size"],
                        }
                    )

    packages_content = "\n".join(stanzas).encode("utf-8")
    packages_path = out_dir / "Packages"
    packages_path.write_bytes(packages_content)

    with gzip.open(out_dir / "Packages.gz", "wb", compresslevel=9) as f:
        f.write(packages_content)
    with bz2.open(out_dir / "Packages.bz2", "wb", compresslevel=9) as f:
        f.write(packages_content)
    with lzma.open(out_dir / "Packages.xz", "wb", preset=9) as f:
        f.write(packages_content)

    # Generate depictions & sileo-featured.json
    featured_banners = []
    for pkg_id, info in packages_by_id.items():
        sileo_json = build_sileo_depiction(
            pkg_id, info["latest_fields"], info["versions"], repo_url
        )
        (depictions_dir / f"{pkg_id}.json").write_text(
            json.dumps(sileo_json, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        web_html = build_web_depiction(pkg_id, info["latest_fields"], info["versions"])
        (web_depictions_dir / f"{pkg_id}.html").write_text(web_html, encoding="utf-8")
        featured_banners.append(
            {
                "url": f"{repo_url}/banner.png",
                "title": info["latest_fields"].get("Name", pkg_id),
                "package": pkg_id,
                "hideShadow": False,
            }
        )

    sileo_featured = {
        "class": "FeaturedBannersView",
        "itemSize": "{263, 148}",
        "itemCornerRadius": 10,
        "banners": featured_banners,
    }
    (out_dir / "sileo-featured.json").write_text(
        json.dumps(sileo_featured, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Generate icons & banner
    generate_png_icon(out_dir / "CydiaIcon.png", 64)
    generate_png_icon(out_dir / "CydiaIcon@2x.png", 128)
    generate_png_icon(out_dir / "CydiaIcon@3x.png", 192)
    generate_png_icon(out_dir / "banner.png", 256)

    # Generate Release file
    idx_files = ["Packages", "Packages.gz", "Packages.bz2", "Packages.xz"]
    idx_hashes = {name: file_hashes(out_dir / name) for name in idx_files}
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S UTC"
    )

    release_lines = [
        f"Origin: {config['origin']}",
        f"Label: {config['label']}",
        "Suite: stable",
        "Version: 1.0",
        "Codename: ios",
        f"Date: {now_utc}",
        "Architectures: iphoneos-arm iphoneos-arm64 iphoneos-arm64e",
        "Components: main",
        f"Description: {config['description']}",
        "MD5Sum:",
    ]
    for name in idx_files:
        release_lines.append(f" {idx_hashes[name]['md5']} {idx_hashes[name]['size']} {name}")
    release_lines.append("SHA1:")
    for name in idx_files:
        release_lines.append(f" {idx_hashes[name]['sha1']} {idx_hashes[name]['size']} {name}")
    release_lines.append("SHA256:")
    for name in idx_files:
        release_lines.append(f" {idx_hashes[name]['sha256']} {idx_hashes[name]['size']} {name}")
    release_lines.append("SHA512:")
    for name in idx_files:
        release_lines.append(f" {idx_hashes[name]['sha512']} {idx_hashes[name]['size']} {name}")

    (out_dir / "Release").write_text("\n".join(release_lines) + "\n", encoding="utf-8")

    # Generate landing page index.html
    pkg_cards = []
    for pkg_id, info in packages_by_id.items():
        lf = info["latest_fields"]
        vers_badges = " ".join(
            f"<a class='badge' href='debs/{v['deb_name']}'>v{v['version']} ({v['arch']})</a>"
            for v in info["versions"]
        )
        pkg_cards.append(
            f"<div class='pkg'>"
            f"<h3><a href='depictions/web/{pkg_id}.html'>{lf.get('Name', pkg_id)}</a> <code>{pkg_id}</code></h3>"
            f"<p>{lf.get('Description', '')}</p>"
            f"<div class='badges'>{vers_badges}</div>"
            f"</div>"
        )
    pkg_cards_html = "\n".join(pkg_cards)

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{config['origin']}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 32px 16px; }}
  .container {{ max-width: 720px; margin: 0 auto; }}
  .hero {{ background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 28px; text-align: center; margin-bottom: 24px; }}
  .hero img {{ width: 64px; height: 64px; border-radius: 14px; margin-bottom: 12px; }}
  h1 {{ margin: 0 0 8px; font-size: 1.75rem; }}
  p.sub {{ color: #94a3b8; margin: 0 0 20px; }}
  .buttons {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }}
  .btn {{ display: inline-block; padding: 10px 18px; border-radius: 10px; font-weight: 600; text-decoration: none; color: #fff; }}
  .btn-sileo {{ background: #0d9488; }}
  .btn-zebra {{ background: #4f46e5; }}
  .repo-box {{ margin-top: 16px; background: #0f172a; padding: 10px 14px; border-radius: 8px; font-family: monospace; color: #cbd5e1; display: inline-block; }}
  .pkg {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-bottom: 14px; }}
  .pkg h3 {{ margin: 0 0 6px; }}
  .pkg h3 a {{ color: #f8fafc; text-decoration: none; }}
  .pkg code {{ font-size: 0.8rem; color: #94a3b8; font-weight: normal; margin-left: 8px; }}
  .pkg p {{ color: #cbd5e1; margin: 0 0 12px; }}
  .badges {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .badge {{ background: #334155; color: #e2e8f0; padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; text-decoration: none; }}
</style>
</head>
<body>
  <div class="container">
    <div class="hero">
      <img src="CydiaIcon@2x.png" alt="Repo Icon">
      <h1>{config['origin']}</h1>
      <p class="sub">{config['description']}</p>
      <div class="buttons">
        <a class="btn btn-sileo" href="sileo://source/{repo_url}/">Add to Sileo</a>
        <a class="btn btn-zebra" href="zbra://sources/add/{repo_url}/">Add to Zebra</a>
      </div>
      <div><span class="repo-box">{repo_url}/</span></div>
    </div>
    <h2>Available Packages</h2>
    {pkg_cards_html}
  </div>
</body>
</html>
"""
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Successfully built APT repository in {out_dir} ({len(stanzas)} package entries).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
