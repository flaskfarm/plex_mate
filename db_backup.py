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


def restore(backup_path, db_path, stamp, sqlite_bin=None):
    """backup_path를 db_path 자리에 되돌린다. (되돌린 경로 목록, 옆에 남긴 이전 파일 목록)을 돌려준다.

    Plex가 꺼져 있어야 한다(호출하는 쪽이 확인한다). 지금 DB와 -wal/-shm은 지우지 않고
    `.before_restore_<stamp>`를 붙여 같은 폴더에 남긴다. 같은 시각의 blobs 백업이 옆에 있으면 함께 되돌린다.
    """
    root, ext = os.path.splitext(db_path)
    stem = os.path.basename(root)
    # 이름 규칙이 맞는 백업만 받는다. blobs 백업이나 엉뚱한 파일이 본 DB를 덮지 않게
    matched = re.match(rf"^{re.escape(stem)}_(\d{{8}}_\d{{6}}){re.escape(ext)}$", os.path.basename(backup_path))
    if not matched:
        raise ValueError(f"백업 파일 이름이 {stem}_YYYYMMDD_HHMMSS{ext} 형식이 아닙니다.")
    pairs = [(backup_path, db_path)]
    blobs_backup = os.path.join(os.path.dirname(backup_path), f"{stem}.blobs_{matched.group(1)}{ext}")
    if os.path.exists(blobs_backup):
        pairs.append((blobs_backup, f"{root}.blobs{ext}"))

    need = sum(os.path.getsize(source) for source, _ in pairs)
    free = shutil.disk_usage(os.path.dirname(db_path)).free
    if free < need * 1.1:
        raise RuntimeError(f"공간 부족: {os.path.dirname(db_path)} (필요 {need >> 20}MB, 여유 {free >> 20}MB)")

    restored, kept, staged = [], [], []
    try:
        # 전부 옆에 받아 놓은 뒤에 바꿔치기한다. 복사 중 실패하면 지금 DB는 그대로다
        for source, target in pairs:
            part = target + '.restore_part'
            staged.append(part)
            shutil.copyfile(source, part)
            if os.path.getsize(part) != os.path.getsize(source):
                raise RuntimeError(f"복사한 파일 크기가 다릅니다: {part}")
            # 받아 놓은 로컬 사본을 검사한다(NFS 위 원본을 직접 검사하면 매우 느리다)
            if sqlite_bin and not verify(part, sqlite_bin):
                raise RuntimeError(f"백업 파일 무결성 검사 실패: {source}")
            if os.path.exists(target):  # Plex가 읽을 수 있게 원래 파일의 권한·소유자를 따른다
                st = os.stat(target)
                os.chmod(part, st.st_mode & 0o7777)
                try:
                    os.chown(part, st.st_uid, st.st_gid)
                except (AttributeError, OSError):  # 윈도우, 권한 없음
                    pass
        for (source, target), part in zip(pairs, staged):
            for suffix in ('', '-wal', '-shm'):
                if os.path.exists(target + suffix):
                    aside = f"{target}{suffix}.before_restore_{stamp}"
                    os.replace(target + suffix, aside)
                    kept.append(aside)
            os.replace(part, target)
            restored.append(target)
    finally:
        for part in staged:
            if os.path.exists(part):
                os.remove(part)
    return restored, kept


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

        # 복원: 지금 DB는 옆에 남고, 같은 시각 blobs 백업도 함께 돌아온다
        live = os.path.join(root, 'live', 'lib.db')
        os.makedirs(os.path.dirname(live))
        for path, value in ((live, 'now'), (live[:-3] + '.blobs.db', 'now-blobs')):
            c = sqlite3.connect(path)
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('CREATE TABLE v(x)')
            c.execute('INSERT INTO v VALUES(?)', (value,))
            c.commit()
            c.close()
        os.chmod(live, 0o666)
        bdir = os.path.join(root, 'bk')
        for path in (live, live[:-3] + '.blobs.db'):
            backup(path, bdir, work, '20260202_000000', 0, cli)
        for path, value in ((live, 'later'), (live[:-3] + '.blobs.db', 'later-blobs')):
            c = sqlite3.connect(path)
            c.execute('UPDATE v SET x = ?', (value,))
            c.commit()
            c.close()
        open(live + '-wal', 'wb').close()  # 비정상 종료로 남은 WAL 흉내
        for bad in ('lib.blobs_20260202_000000.db', 'lib_wrong.db'):
            try:
                restore(os.path.join(bdir, bad), live, '20260303_000000', cli)
                raise AssertionError('이름이 틀린 백업은 거절해야 한다')
            except ValueError:
                pass
        restored, kept = restore(os.path.join(bdir, 'lib_20260202_000000.db'), live, '20260303_000000', cli)
        assert restored == [live, live[:-3] + '.blobs.db'], restored

        def value_of(path):
            c = sqlite3.connect(path)
            try:
                return c.execute('SELECT x FROM v').fetchone()[0]
            finally:
                c.close()
        assert value_of(live) == 'now' and value_of(live[:-3] + '.blobs.db') == 'now-blobs'
        assert live + '.before_restore_20260303_000000' in kept and live + '-wal.before_restore_20260303_000000' in kept, kept
        assert value_of(live + '.before_restore_20260303_000000') == 'later'
        assert os.stat(live).st_mode & 0o777 == 0o666
        assert not [n for n in os.listdir(os.path.dirname(live)) if n.endswith('.restore_part')]
    print('ok' if cli else 'ok (sqlite3 명령이 없어 검사 단계는 빠짐)')
