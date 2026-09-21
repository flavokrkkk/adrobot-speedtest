#!/usr/bin/env python3
"""Замер скорости загрузки с этого компьютера.

Делает N последовательных GET-запросов к одному адресу (например, тяжёлой
картинке), дожидается полного ответа на каждый, считает среднее время
запроса, суммарный объём и скорость в МБ/с.

Только стандартная библиотека, Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CHUNK_SIZE = 64 * 1024
MEGABYTE = 1_000_000  # десятичный мегабайт, как считают провайдеры
USER_AGENT = "speedtest/1.0 (+https://github.com/flavokrkkk)"


@dataclass(frozen=True)
class Attempt:
    """Один запрос: сколько заняло и сколько байт скачано."""

    seconds: float
    size: int


@dataclass(frozen=True)
class Summary:
    """Итог по серии последовательных запросов."""

    attempts: tuple[Attempt, ...]

    @property
    def total_bytes(self) -> int:
        return sum(a.size for a in self.attempts)

    @property
    def total_seconds(self) -> float:
        return sum(a.seconds for a in self.attempts)

    @property
    def average_seconds(self) -> float:
        return self.total_seconds / len(self.attempts)

    @property
    def megabytes_per_second(self) -> float:
        # Запросы идут строго последовательно, поэтому скорость —
        # весь объём за всё время, а не среднее по отдельным замерам.
        return self.total_bytes / MEGABYTE / self.total_seconds

    @property
    def megabits_per_second(self) -> float:
        return self.megabytes_per_second * 8

    def as_dict(self) -> dict[str, int | float]:
        """Итог в виде словаря для машинного вывода (--json)."""
        return {
            "runs": len(self.attempts),
            "average_seconds": self.average_seconds,
            "total_bytes": self.total_bytes,
            "megabytes_per_second": self.megabytes_per_second,
            "megabits_per_second": self.megabits_per_second,
        }


def with_cache_buster(url: str, token: str) -> str:
    """Добавляет к URL уникальный параметр, чтобы ответ не пришёл из кэша."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("_speedtest", token))
    return urlunsplit(parts._replace(query=urlencode(query)))


def download(url: str, timeout: float) -> Attempt:
    """Скачивает ответ целиком и возвращает время и размер."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}
    )
    size = 0
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        while chunk := response.read(CHUNK_SIZE):
            size += len(chunk)
    return Attempt(seconds=time.perf_counter() - started, size=size)


def measure(
    url: str,
    runs: int,
    timeout: float,
    cache_bust: bool = True,
    on_attempt: Callable[[int, Attempt], None] | None = None,
) -> Summary:
    """Выполняет `runs` последовательных запросов к `url`."""
    if runs < 1:
        raise ValueError("runs must be >= 1")
    attempts: list[Attempt] = []
    for index in range(1, runs + 1):
        target = with_cache_buster(url, f"{time.time_ns()}-{index}") if cache_bust else url
        attempt = download(target, timeout)
        attempts.append(attempt)
        if on_attempt:
            on_attempt(index, attempt)
    return Summary(tuple(attempts))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Замер скорости загрузки: N последовательных запросов к URL."
    )
    parser.add_argument("url", help="адрес, куда стучаться (лучше тяжёлая картинка)")
    parser.add_argument("--runs", type=int, default=10, help="число запросов (по умолчанию 10)")
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="таймаут одного запроса в секундах"
    )
    parser.add_argument(
        "--no-cache-bust",
        action="store_true",
        help="не добавлять к URL параметр против кэширования",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="печатать итог одной строкой JSON вместо отчёта и прогресса",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def report(index: int, attempt: Attempt) -> None:
        print(
            f"[{index:>2}/{args.runs}] {attempt.seconds:8.3f} с   "
            f"{attempt.size / MEGABYTE:8.2f} МБ",
            flush=True,
        )

    try:
        summary = measure(
            args.url,
            runs=args.runs,
            timeout=args.timeout,
            cache_bust=not args.no_cache_bust,
            on_attempt=None if args.json else report,
        )
    except ValueError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as error:
        print(f"Ошибка: сервер ответил {error.code} {error.reason}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(f"Ошибка: не удалось скачать {args.url}: {error}", file=sys.stderr)
        return 1

    if args.json:
        # Одна строка, без экранирования не-ASCII — чтобы удобно парсить в пайпе.
        print(json.dumps(summary.as_dict(), ensure_ascii=False))
        return 0

    print()
    print(f"Запросов:            {len(summary.attempts)}")
    print(f"Среднее время:       {summary.average_seconds:.3f} с")
    print(f"Скачано всего:       {summary.total_bytes / MEGABYTE:.2f} МБ ({summary.total_bytes} байт)")
    print(f"Скорость:            {summary.megabytes_per_second:.2f} МБ/с "
          f"({summary.megabits_per_second:.1f} Мбит/с)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
