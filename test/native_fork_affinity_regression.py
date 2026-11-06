"""Hardware-free regression for the shipped ARM64 PyTorch/OpenMP fork mask collapse."""
import multiprocessing as mp
import os
import main_optimized  # noqa: F401 -- reproducer requires the real import graph


def worker(connection):
    connection.send(sorted(os.sched_getaffinity(0)))
    connection.close()


if __name__ == '__main__':
    allowed = sorted(os.sched_getaffinity(0))
    assert len(allowed) > 1, 'run in an isolated tool container with at least two allowed CPUs'
    context = mp.get_context('fork')
    processes, connections = [], []
    try:
        for _ in range(3):
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(target=worker, args=(sender,))
            process.start()
            sender.close()
            processes.append(process)
            connections.append(receiver)
        results = []
        for connection in connections:
            assert connection.poll(15), 'worker did not report affinity'
            results.append(connection.recv())
        for process in processes:
            process.join(timeout=5)
            assert process.exitcode == 0
        print('parent=', allowed, 'workers=', results, 'OMP_PROC_BIND=', os.environ.get('OMP_PROC_BIND'), flush=True)
        assert all(result == allowed for result in results), 'worker CPU affinity narrowed after fork'
        print('PASS all three fork workers retain the parent allowed mask')
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        for connection in connections:
            connection.close()
