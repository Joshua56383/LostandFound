#!/usr/bin/env python3
"""
Update SQLite DB media paths using `dedupe_mapping.json`.

Creates a DB backup before applying changes. Updates any TEXT/varchar column
named `image` or `file` across all tables where the value matches a duplicate
path (relative to media/) and replaces it with the canonical relative path.

Usage: python scripts/update_db_media_paths.py
"""
import os
import sqlite3
import shutil
import json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DB = os.path.join(ROOT, 'CampusLostFound', 'db.sqlite3')
DB_BACKUP = os.path.join(ROOT, 'CampusLostFound', 'db.before_media_path_update.sqlite3')
MAPPING = os.path.join(ROOT, 'dedupe_mapping.json')


def rel_from_abs(abs_path):
    # Expect paths under CampusLostFound/media/
    parts = abs_path.replace('\\', '/').split('/CampusLostFound/media/')
    if len(parts) == 2:
        return parts[1]
    # fallback: if path contains '/media/'
    parts = abs_path.replace('\\', '/').split('/media/')
    if len(parts) == 2:
        return parts[1]
    return os.path.basename(abs_path)


def load_mapping():
    if not os.path.exists(MAPPING):
        raise FileNotFoundError('dedupe_mapping.json not found; run dedupe first')
    with open(MAPPING, 'r', encoding='utf-8') as fh:
        m = json.load(fh)
    mapping = m.get('mapping', {})
    rel_map = {}
    for dup_abs, canon_abs in mapping.items():
        dup_rel = rel_from_abs(dup_abs)
        canon_rel = rel_from_abs(canon_abs)
        rel_map[dup_rel.replace('\\','/')] = canon_rel.replace('\\','/')
    return rel_map


def find_candidate_columns(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    candidates = []
    for t in tables:
        try:
            cur.execute(f'PRAGMA table_info({t})')
            cols = cur.fetchall()
        except Exception:
            continue
        for col in cols:
            cname = col[1]
            # target columns named 'image' or 'file'
            if cname.lower() in ('image', 'file', 'profile_picture'):
                candidates.append((t, cname))
    return candidates


def apply_updates(db_path, rel_map):
    shutil.copy2(db_path, DB_BACKUP)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    candidates = find_candidate_columns(conn)
    updated = []
    for table, col in candidates:
        for dup_rel, canon_rel in rel_map.items():
            # update rows matching duplicate path
            cur.execute(f"SELECT rowid, {col} FROM {table} WHERE {col} = ?", (dup_rel,))
            rows = cur.fetchall()
            if not rows:
                continue
            cur.execute(f"UPDATE {table} SET {col} = ? WHERE {col} = ?", (canon_rel, dup_rel))
            updated.append({'table': table, 'column': col, 'from': dup_rel, 'to': canon_rel, 'count': cur.rowcount})
    conn.commit()
    conn.close()
    return updated


def main():
    rel_map = load_mapping()
    if not rel_map:
        print('No mapping entries to apply.')
        return 0
    print('Backing up DB to', DB_BACKUP)
    updates = apply_updates(DB, rel_map)
    print('Applied updates:')
    for u in updates:
        print(f" - {u['count']} rows: {u['table']}.{u['column']} {u['from']} -> {u['to']}")
    if not updates:
        print('No rows updated.')
    return 0


if __name__ == '__main__':
    main()
