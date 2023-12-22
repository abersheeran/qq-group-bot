import abc
import re
from typing import Any, Callable

from loguru import logger


def command[C: Callable](name: str) -> Callable[[C], C]:
    def wrapper(func: C) -> C:
        func.command = name
        return func

    return wrapper


class CommandMatcher(abc.ABC):
    commands: dict[str, str]
    command_pattern: re.Pattern[str]

    def __init_subclass__(cls) -> None:
        cls.commands = {}

        for name, func in cls.__dict__.items():
            if not hasattr(func, "command"):
                continue
            cls.commands[func.command] = name

        cls.command_pattern = re.compile(
            r"^\s*/(" + "|".join(cls.commands.keys()) + r")\s*(.*)$"
        )

    @classmethod
    def match(cls, content: str) -> tuple[str, str]:
        match = cls.command_pattern.match(content)
        if match is None:
            return "", content
        return cls.commands[match.group(1)], match.group(2)

    def __init__(self, content: str, **kwargs: Any) -> None:
        self.command, self.content = self.match(content)
        logger.debug(f"Matched command: {self.command}")
        self.kwargs = kwargs
        self.run = getattr(self, self.command, self.unknown_command)

    def __await__(self) -> Any:
        return self.run(self.content, **self.kwargs).__await__()

    @abc.abstractmethod
    async def unknown_command(self, content: str, **kwargs: Any) -> None:
        raise NotImplementedError
