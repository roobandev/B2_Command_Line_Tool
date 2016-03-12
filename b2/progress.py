######################################################################
#
# File: progress.py
#
# Copyright 2015 Backblaze Inc. All Rights Reserved.
#
# License https://www.backblaze.com/using_b2_code.html
#
######################################################################

from abc import ABCMeta, abstractmethod
import six
import time

try:
    from tqdm import tqdm  # displays a nice progress bar
except ImportError:
    tqdm = None  # noqa


@six.add_metaclass(ABCMeta)
class ProgressListener(object):
    """
    Interface expected by B2Api upload and download methods to report
    on progress.

    This interface just accepts the number of bytes transferred so far.
    Subclasses will need to know the total size if they want to report
    a percent done.
    """

    @abstractmethod
    def set_total_bytes(self, total_byte_count):
        """
        Always called before __enter__ to set the expected total number of bytes.

        May be called more than once if an upload is retried.
        """

    @abstractmethod
    def bytes_completed(self, byte_count):
        """
        Reports that the given number of bytes have been transferred
        so far.  This is not a delta, it is the total number of bytes
        transferred so far.
        """

    @abstractmethod
    def close(self):
        """
        Must be called when you're done with the listener.
        """

    def __enter__(self):
        """
        standard context manager method
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        standard context manager method
        """
        self.close()


class TqdmProgressListener(ProgressListener):
    def __init__(self, description):
        self.description = description
        self.tqdm = None  # set in set_total_bytes()
        self.prev_value = 0

    def set_total_bytes(self, total_byte_count):
        if self.tqdm is None:
            self.tqdm = tqdm(
                desc=self.description,
                total=total_byte_count,
                unit='B',
                unit_scale=True,
                leave=True,
                miniters=1
            )

    def bytes_completed(self, byte_count):
        # tqdm doesn't support running the progress bar backwards,
        # so on an upload retry, it just won't move until it gets
        # past the point where it failed.
        if self.prev_value < byte_count:
            self.tqdm.update(byte_count - self.prev_value)
            self.prev_value = byte_count

    def close(self):
        if self.tqdm is not None:
            self.tqdm.close()


class SimpleProgressListener(ProgressListener):
    def __init__(self, description):
        self.desc = description
        self.complete = 0
        self.last_time = time.time()
        self.any_printed = False

    def set_total_bytes(self, total_byte_count):
        self.total = total_byte_count

    def bytes_completed(self, byte_count):
        now = time.time()
        elapsed = now - self.last_time
        if 3 <= elapsed and self.total != 0:
            if not self.any_printed:
                print(self.desc)
            print('     %d%%' % int(100.0 * byte_count / self.total))
            self.last_time = now
            self.any_printed = True

    def close(self):
        if self.any_printed:
            print('    DONE.')


class DoNothingProgressListener(ProgressListener):
    def set_total_bytes(self, total_byte_count):
        pass

    def bytes_completed(self, byte_count):
        pass

    def close(self):
        pass


def make_progress_listener(description, quiet):
    if quiet:
        return DoNothingProgressListener()
    elif tqdm is not None:
        return TqdmProgressListener(description)
    else:
        return SimpleProgressListener(description)


class StreamWithProgress(object):
    """
    Wraps a file-like object and updates a ProgressListener
    as data is read and written.
    """

    def __init__(self, stream, progress_listener, offset=0):
        """

        :param stream: the stream to read from or write to
        :param progress_listener: the listener that we tell about progress
        :param offset: the starting byte offset in the file
        :return: None
        """
        assert progress_listener is not None
        self.stream = stream
        self.progress_listener = progress_listener
        self.bytes_completed = offset

    def __enter__(self):
        return self

    def read(self, size=None):
        if size is None:
            data = self.stream.read()
        else:
            data = self.stream.read(size)
        self._update(len(data))
        return data

    def write(self, data):
        self.stream.write(data)
        self._update(len(data))

    def _update(self, delta):
        self.bytes_completed += delta
        self.progress_listener.bytes_completed(self.bytes_completed)