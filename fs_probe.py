"""자막 파일이 살아 있는지 OS 스레드에서, 시간 제한을 두고 확인한다. (프레임워크 의존 없음)

자체 점검: python3 fs_probe.py  /  python3 fs_probe.py gevent
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

OK, DEAD, UNKNOWN = 'ok', 'dead', 'unknown'


def executor(workers):
    """OS 스레드 풀을 돌려준다.

    셀러리 gevent 풀에서는 threading이 그린릿으로 바뀌어 있어, 일반 ThreadPoolExecutor를 쓰면
    멈춘 파일 조회 하나가 작업자 전체를 세우고 시간 제한도 걸리지 않는다.
    """
    try:
        from gevent import monkey
        if monkey.is_module_patched('threading'):
            from gevent.threadpool import ThreadPoolExecutor as NativeExecutor
            return NativeExecutor(workers)
    except ImportError:
        pass
    return ThreadPoolExecutor(workers)


def probe(sub_path, video_path):
    try:
        if os.path.exists(sub_path):
            return OK
        # 영상까지 안 보이면 자막이 지워진 게 아니라 마운트가 내려갔거나 영상째 없어진 것이다
        if video_path and os.path.exists(video_path):
            return DEAD
    except Exception:  # 확인하다 난 오류를 '죽은 자막'으로 치지 않는다
        pass
    return UNKNOWN


def probe_many(pool, items, timeout):
    """items [(key, 자막 경로, 영상 경로)]를 확인해 ({key: 상태}, 시간 안에 답이 없던 개수)를 돌려준다.

    답이 없는 것은 DEAD가 아니라 UNKNOWN이다.
    """
    futures = {pool.submit(probe, sub, video): key for key, sub, video in items}
    deadline = time.monotonic() + timeout
    result, hung = {}, 0
    # concurrent.futures.wait는 gevent 패치 시점에 따라 동작이 달라져 쓰지 않는다
    for future, key in futures.items():
        try:
            result[key] = future.result(timeout=max(0, deadline - time.monotonic()))
        except Exception:
            result[key] = UNKNOWN
            hung += not future.done()
    return result, hung


if __name__ == '__main__':
    import signal
    import sys
    import tempfile

    use_gevent = sys.argv[1:] == ['gevent']
    if use_gevent:
        from gevent import monkey
        monkey.patch_all()
    signal.alarm(60)  # 점검 자체가 멈추면 죽인다

    with tempfile.TemporaryDirectory() as root:
        video = os.path.join(root, 'movie.mkv')
        sub = os.path.join(root, 'movie.ko.srt')
        fifo = os.path.join(root, 'hang')
        for path in (video, sub):
            open(path, 'w').close()
        os.mkfifo(fifo)

        real_exists = os.path.exists

        def fake_exists(path):
            if path == 'HANG':  # 멈춘 FUSE 흉내: 쓰는 쪽이 생길 때까지 진짜로 막힌다
                with open(fifo):
                    pass
                return False
            if path is None:
                raise TypeError('경로 없음')
            return real_exists(path)

        os.path.exists = fake_exists
        pool = executor(8)
        try:
            started = time.time()
            result, hung = probe_many(pool, [
                ('ok', sub, video),
                ('dead', os.path.join(root, 'gone.srt'), video),
                ('unmounted', '/no/such/mount/a.srt', '/no/such/mount/a.mkv'),
                ('no_video', os.path.join(root, 'gone.srt'), None),
                ('error', None, video),
                ('hang', 'HANG', video),
            ], timeout=2)
            took = time.time() - started
            assert result == {'ok': OK, 'dead': DEAD, 'unmounted': UNKNOWN, 'no_video': UNKNOWN,
                              'error': UNKNOWN, 'hang': UNKNOWN}, result
            assert hung == 1, hung
            assert 1.5 < took < 10, took  # 멈춘 조회를 기다리지 않고 제한 시간에 돌아온다
            # 멈춘 조회가 남아 있어도 다음 묶음은 정상 처리된다
            result, hung = probe_many(pool, [(i, sub, video) for i in range(20)], timeout=5)
            assert hung == 0 and set(result.values()) == {OK}, (result, hung)
        finally:
            os.path.exists = real_exists
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)  # 막힌 스레드를 풀어 준다
            os.close(fd)
            pool.shutdown(wait=False)
    print('ok', '(gevent)' if use_gevent else '')
