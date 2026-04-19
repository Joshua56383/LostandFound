#!/usr/bin/env python3
"""
Safe media deduplication helper.

Usage:
  python scripts/dedupe_media.py [--apply]

By default (no flags) it runs a dry-run that creates a mapping JSON and
backs up any duplicate files into `cleanup_backups/<timestamp>/` without
removing or changing originals. With `--apply` it will replace duplicate
files with copies of the canonical file (non-destructive backup kept).

This script reads `cleanup_scan_report.json` produced earlier.
"""
import os
import sys
import json
import shutil
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
REPORT = os.path.join(ROOT, 'cleanup_scan_report.json')
BACKUP_ROOT = os.path.join(ROOT, 'cleanup_backups')
MAPPING_OUT = os.path.join(ROOT, 'dedupe_mapping.json')


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)


def copy_to_backup(src, backup_root):
    rel = os.path.relpath(src, ROOT)
    dest = os.path.join(backup_root, rel)
    ensure_dir(os.path.dirname(dest))
    shutil.copy2(src, dest)
    return dest


def main(apply_changes=False):
    if not os.path.exists(REPORT):
        print('Missing cleanup_scan_report.json; run scan first.')
        return 2

    with open(REPORT, 'r', encoding='utf-8') as fh:
        report = json.load(fh)

    dup_groups = report.get('duplicate_groups', {})
    timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    backup_dir = os.path.join(BACKUP_ROOT, timestamp)
    ensure_dir(backup_dir)

    mapping = {}
    moved_count = 0
    backed_up = []

    for h, paths in dup_groups.items():
        if not paths:
            continue
        canonical = paths[0]
        # ensure canonical exists
        if not os.path.exists(canonical):
            # try to find an existing one
            existing = next((p for p in paths if os.path.exists(p)), None)
            if existing:
                canonical = existing
            else:
                # nothing to do
                continue

        for p in paths:
            if os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(canonical)):
                continue
            if not os.path.exists(p):
                continue
            # backup the duplicate file
            bkp = copy_to_backup(p, backup_dir)
            backed_up.append({'path': p, 'backup': bkp})
            mapping[p] = canonical
            moved_count += 1
            if apply_changes:
                # replace duplicate with a copy of canonical
                try:
                    os.remove(p)
                except Exception:
                    pass
                ensure_dir(os.path.dirname(p))
                shutil.copy2(canonical, p)

    # write mapping
    with open(MAPPING_OUT, 'w', encoding='utf-8') as fh:
        json.dump({'timestamp': timestamp, 'mapping': mapping, 'backed_up': backed_up}, fh, indent=2)

    print(f'DRY RUN: backups placed at {backup_dir}')
    print(f'Found {len(dup_groups)} duplicate groups; prepared {moved_count} duplicate entries')
    if apply_changes:
        print('Applied changes: duplicates replaced with canonical copies (backups kept).')
    else:
        print('No changes applied. Re-run with --apply to replace duplicates with canonical copies.')
    return 0


if __name__ == '__main__':
    apply_flag = '--apply' in sys.argv[1:]
    rc = main(apply_changes=apply_flag)
    sys.exit(rc)
