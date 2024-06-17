from copy import deepcopy
from .trajectory_point import TrajectoryPoint


class TrajectoryBuffer:
    def __init__(self) -> None:
        self._buffer = []
        self.size = 0
        self.nq = 0
        self.nv = 0

    def initialize(self, size: int, start: TrajectoryPoint):
        self.size = size
        self.buffer = [None] * self.size
        self.nq = start.q.shape[0]
        self.nv = start.v.shape[0]
        for i in range(len(self.buffer)):
            self.buffer[i] = deepcopy(start)

    def add(self, trajectory_point: TrajectoryPoint):
        assert self.nq == trajectory_point.q.shape[0]
        assert self.nv == trajectory_point.v.shape[0]
        if len(self.buffer) >= self.size:
            self.buffer.pop(0)
        self.buffer.append(trajectory_point)

    def fill_buffer(self, trajectory_point: TrajectoryPoint):
        for _ in range(self.size - self.buffer_size()):
            self.add(trajectory_point)

    def buffer_size(self):
        return self.size - self.buffer.count(None)

    def get_buffer(self):
        return self._buffer.copy()
