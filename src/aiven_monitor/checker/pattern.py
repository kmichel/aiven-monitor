from typing import List, Optional

import trio
from httpx._decoders import TextDecoder
from regex.regex import Pattern


class DecodingError(Exception):
    pass


async def search_pattern(
        pattern: Pattern, chunks: List[bytes], encoding: Optional[str]
) -> bool:
    # Do we really spawn a whole thread just to run a regular expression ?
    #
    # Yes, because we might not be in control of the regular expression
    # which could run for an indefinite amount of time.
    #
    # We also leverage the regex module which releases the GIL (unlike the
    # standard re module) and allows other coroutines to run.
    #
    # Note that trio uses a thread pool here, we're not spawning a new
    # thread for each request :)
    #
    # However, trio can't really cancel a thread, if the caller cancels this
    # call, then the thread will keep running until it's finished. The proper
    # solution here is to use a entire separate process, one we can kill.
    return await trio.to_thread.run_sync(
        search_sync, pattern, chunks, encoding, cancellable=True
    )


def search_sync(
        pattern: Pattern, chunks: List[bytes], encoding: Optional[str]
) -> bool:
    try:
        # I wish we didn't call protected httpx code here
        # but it's better than rewriting and testing their
        # decoder, and this separates the concerns of
        # handling large vs. malformed responses.
        text_chunks = []
        decoder = TextDecoder(encoding=encoding)
        for chunk in chunks:
            text_chunks.append(decoder.decode(chunk))
        text_chunks.append(decoder.flush())
    except ValueError as value_error:
        raise DecodingError(str(value_error))
    else:
        content = ''.join(text_chunks)
        match = pattern.search(content, concurrent=True)
        return match is not None
