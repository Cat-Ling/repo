# Cat-Ling's Sileo & Zebra APT Repository (`https://cat-ling.github.io/repo/`)

An automated, zero-git-bloat APT repository compatible with **Sileo**, **Zebra**, and **Cydia**, hosted on GitHub Pages.

## Add to Your Package Manager

- **Repository URL:** `https://cat-ling.github.io/repo/`
- **One-Tap Links:**
  - `sileo://source/https://cat-ling.github.io/repo/`
  - `zbra://sources/add/https://cat-ling.github.io/repo/`

---

## Architecture & How It Stays Clean

1. **Zero Binary Bloat in Git History**:
   - No `.deb` binaries or generated `Packages`/`Release` archives are ever committed to the git repository.
   - Instead, [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) runs [`build_repo.py`](build_repo.py) on Ubuntu, fetches `.deb` assets and release changelogs via the GitHub Releases API from the repositories configured in [`repos.json`](repos.json) (`Cat-Ling/AppSync`, `Cat-Ling/appinst`), builds `_site/`, and publishes it directly to GitHub Pages via `actions/upload-pages-artifact` + `actions/deploy-pages`.
2. **Instant Cross-Repository Webhook (`repository_dispatch`)**:
   - Whenever a release is published on [`Cat-Ling/AppSync`](https://github.com/Cat-Ling/AppSync) (or [`Cat-Ling/appinst`](https://github.com/Cat-Ling/appinst)), its release workflow fires a `repository_dispatch` (`release-published`) event to `Cat-Ling/repo`, immediately rebuilding and deploying the updated APT repository and Sileo/Zebra depictions.
3. **Full Sileo & Zebra Metadata Support**:
   - Generates `Packages`, `Packages.xz`, `Packages.bz2`, `Packages.gz`, and `Release` (with `MD5Sum`, `SHA1`, `SHA256`, and `SHA512` checksums).
   - Preserves historical `.deb` versions in `Packages` so Sileo and Zebra support version selection / downgrades.
   - Generates native Sileo JSON depictions (`depictions/<pkg>.json`), Zebra/web depictions (`depictions/web/<pkg>.html`), and `sileo-featured.json` populated with release history and changelogs.
