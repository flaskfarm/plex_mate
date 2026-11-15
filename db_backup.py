"""Plex DB 백업. 실행 중인 DB의 일관된 사본을 만들고, 검사한 뒤, 백업 폴더에 넣는다.

프레임워크에 의존하지 않는다. 자체 점검: python3 db_backup.py [sqlite3 또는 Plex SQLite 경로]
"""
import os
import re
import shutil
import sqlite3
import subprocess
import urllib.parse


def _uri(path, option):
    return f"file:{urllib.parse.quote(os.path.abspath(path))}?{option}"


def snapshot(src, dst):
    """SQLite 온라인 백업으로 src의 한 시점 사본을 dst에 만든다.

    파일 복사와 달리 WAL에만 있는 변경분이 들어가고, Plex가 쓰는 중이어도 깨지지 않는다.
    """
    src_con = sqlite3.connect(_uri(src, 'mode=ro'), uri=True, timeout=60)
    try:
        dst_con = sqlite3.connect(dst)
        try:
            src_con.backup(dst_con)
        finally:
            dst_con.close()
    finally:
        src_con.close()


def verify(path, sqlite_bin):
    """사본의 구조 검사(quick_check)가 ok인지 돌려준다.

    Plex DB는 전용 정렬 규칙(icu_root)을 써서 파이썬 내장 SQLite로는 검사할 수 없다. Plex SQLite로 돌린다.
    """
    # immutable: 검사하면서 사본 옆에 -wal/-shm 파일을 만들지 않는다
    done = subprocess.run([sqlite_bin, _uri(path, 'immutable=1'), 'PRAGMA quick_check;'],
                          capture_output=True, text=True, timeout=3600)
    return done.returncode == 0 and done.stdout.strip() == 'ok'


def prune(backup_dir, stem, ext, max_count):
    """`stem_YYYYMMDD_HHMMSS.ext` 백업 중 최신 max_count개만 남기고 지운 경로를 돌려준다. 0 이하면 지우지 않는다."""
    if max_count <= 0:
        return []
    pattern = re.compile(rf"^{re.escape(stem)}_\d{{8}}_\d{{6}}{re.escape(ext)}$")
    # 이름에 시각이 들어 있어 이름순이 곧 시간순이다
    names = sorted((n for n in os.listdir(backup_dir) if pattern.match(n)), reverse=True)
    removed = []
    for name in names[max_count:]:
        path = os.path.join(backup_dir, name)
        try:
            os.remove(path)
        except OSError:  # 못 지운 옛 백업 때문에 새 백업을 실패로 만들지 않는다
            continue
        removed.append(path)
    return removed


def backup(db_path, backup_dir, work_dir, stamp, max_count=0, sqlite_bin=None):
    """db_path를 backup_dir에 백업한다. (백업 경로, 지운 옛 백업 목록)을 돌려주고 실패하면 예외를 낸다.

    sqlite_bin(Plex SQLite 경로)이 없으면 무결성 검사만 건너뛴다.

    사본은 로컬 work_dir에서 만들고 검사한다(NFS 위에서 SQLite를 직접 쓰면 느리고 잠금이 불안하다).
    검사를 통과한 것만 backup_dir로 옮기며, 옛 백업은 새 백업이 자리 잡은 뒤에만 지운다.
    """
    stem, ext = os.path.splitext(os.path.basename(db_path))
    name = f"{stem}_{stamp}{ext}"
    work = os.path.join(work_dir, name)
    final = os.path.join(backup_dir, name)
    part = final + '.part'
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(backup_dir, exist_ok=True)

    need = os.path.getsize(db_path)
    if os.path.exists(db_path + '-wal'):
        need += os.path.getsize(db_path + '-wal')
    for folder in (work_dir, backup_dir):
        free = shutil.disk_usage(folder).free
        if free < need * 1.1:
            raise RuntimeError(f"공간 부족: {folder} (필요 {need >> 20}MB, 여유 {free >> 20}MB)")

    try:
        snapshot(db_path, work)
        if sqlite_bin and not verify(work, sqlite_bin):
            raise RuntimeError(f"백업본 무결성 검사 실패: {name}")
        size = os.path.getsize(work)
        shutil.move(work, part)
        if os.path.getsize(part) != size:
            raise RuntimeError(f"백업 폴더로 옮긴 파일 크기가 다릅니다: {part}")
        os.replace(part, final)  # 완성본만 최종 이름을 갖는다
    finally:
        for leftover in (work, work + '-journal', work + '-wal', work + '-shm', part):
            if os.path.exists(leftover):
                os.remove(leftover)
    return final, prune(backup_dir, stem, ext, max_count)


if __name__ == '__main__':
    import sys
    import tempfile
    import threading

    cli = (sys.argv[1:] or [shutil.which('sqlite3')])[0]  # 없으면 검사 단계만 빼고 점검한다
    with tempfile.TemporaryDirectory() as root:
        src = os.path.join(root, 'plex 원본.db')  # 공백·한글 경로
        con = sqlite3.connect(src)
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA wal_autocheckpoint=0')  # 변경분을 WAL에만 둔다
        con.execute('CREATE TABLE t(a, b)')
        con.executemany('INSERT INTO t VALUES(?, ?)', [(i, 'x' * 500) for i in range(20000)])
        con.commit()

        stop = threading.Event()

        def writer():
            w = sqlite3.connect(src, timeout=60)
            while not stop.is_set():
                # 두 줄을 한 묶음으로 쓴다. 사본에서 줄 수가 홀수면 중간 상태가 찍힌 것
                w.execute("INSERT INTO t VALUES(-1, 'pair')")
                w.execute("INSERT INTO t VALUES(-1, 'pair')")
                w.commit()
            w.close()

        th = threading.Thread(target=writer)
        th.start()
        out = os.path.join(root, 'out')
        work = os.path.join(root, 'work')
        try:
            for i in range(4):
                final, removed = backup(src, out, work, f'20260101_00000{i}', 3, cli)
                chk = sqlite3.connect(final)
                total, pairs = chk.execute("SELECT count(*), sum(b = 'pair') FROM t").fetchone()
                chk.close()
                assert total >= 20000, total  # WAL에만 있던 내용이 들어 있다
                assert (pairs or 0) % 2 == 0, pairs  # 한 시점의 사본이다
        finally:
            stop.set()
            th.join()
            con.close()
        assert len(removed) == 1 and removed[0].endswith('_20260101_000000.db'), removed
        assert sorted(os.listdir(out)) == [f'plex 원본_20260101_00000{i}.db' for i in (1, 2, 3)], os.listdir(out)
        assert os.listdir(work) == [], os.listdir(work)

        # 깨진 사본은 걸러진다
        with open(final, 'r+b') as f:
            f.seek(4096 * 3)
            f.write(b'\xff' * 4096 * 20)
        if cli:
            assert verify(os.path.join(out, 'plex 원본_20260101_000002.db'), cli)
            assert not verify(final, cli)

        # 실패하면 찌꺼기를 남기지 않고 옛 백업도 지우지 않는다
        try:
            backup(os.path.join(root, '없는파일.db'), out, work, '20260101_000009', max_count=1)
            raise AssertionError('예외가 나야 한다')
        except OSError:
            pass
        assert len(os.listdir(out)) == 3 and os.listdir(work) == []
    print('ok' if cli else 'ok (sqlite3 명령이 없어 검사 단계는 빠짐)')
