#!/usr/bin/env python3
"""Install Git repos into explicit directories or ./repo-name."""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import SplitResult, unquote, unquote_to_bytes, urlsplit
from typing import Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple, Union

DEFAULT_REPO_FILENAME = "repo-console.json"


class RepoConfigError(ValueError):
    """A configuration error whose originating location is already attached."""

    def __init__(self, message: str, *, context: Optional[str] = None) -> None:
        self.context = context
        if context is not None:
            message = "{}: {}".format(context, message)
        super().__init__(message)


class RepoCommand:
    def __init__(self, cmd: str, cwd: str, *, context: str = "command") -> None:
        self.cmd = cmd
        self.cwd = cwd
        self.validate(context=context)

    @classmethod
    def from_options(cls, options, *, context: str = "command") -> "RepoCommand":
        if not isinstance(options, dict):
            msg = "expected an object with command or cmd and optional cwd"
            raise RepoConfigError(msg, context=context)
        if "command" in options:
            cmd = options["command"]
            if "cmd" in options and cmd != options["cmd"]:
                msg = "command and cmd must match when both are specified"
                raise RepoConfigError(msg, context=context)
        else:
            cmd = options.get("cmd")
        cwd = options.get("cwd", "$dest")
        return cls(cmd, cwd, context=context)

    def dump_options(self) -> dict:
        return {"cmd": self.cmd, "cwd": self.cwd}

    def validate(self, *, context: str = "command") -> None:
        for key in ("cmd", "cwd"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip() or "\0" in value:
                msg = "{} must be a nonempty string"
                raise RepoConfigError(msg.format(key), context=context)


class RepoSpec:
    """Repo spec with shared address and path rules."""

    OPTION_KEYS = (
        "repo",
        "dest",
        "base_dir",
        "base_url",
        "branch",
        "depth",
        "commands",
    )

    def __init__(
        self,
        repo: Optional[str] = None,
        dest: Optional[str] = None,
        branch: Optional[str] = None,
        depth: Optional[int] = None,
        *,
        commands: Optional[Sequence[RepoCommand]] = None,
        base_dir: Optional[str] = None,
        base_url: Optional[str] = None
    ) -> None:
        self.repo = repo
        self.dest = dest
        self.branch = branch
        self.depth = depth
        self.base_dir = base_dir
        self.base_url = base_url
        self.commands = []
        if commands is not None:
            self.commands = self.copy_commands(commands)
        self.validate()

    @staticmethod
    def copy_commands(commands: Sequence[RepoCommand]) -> List[RepoCommand]:
        """Copy incoming commands so each spec owns its mutable objects."""
        copied = []
        for index, command in enumerate(commands):
            if not isinstance(command, RepoCommand):
                msg = "commands[{}] must be a RepoCommand"
                raise ValueError(msg.format(index))
            context = "commands[{}]".format(index)
            copied.append(RepoCommand(command.cmd, command.cwd, context=context))
        return copied

    def apply_options(self, options: dict) -> None:
        """Override supplied fields without resolving their paths."""
        for key in self.OPTION_KEYS:
            if key not in options:
                continue
            value = options[key]
            if key == "commands":
                value = self.copy_commands(value)
            setattr(self, key, value)

    def dump_options(self) -> dict:
        """Export repo options, including explicit null branch and depth values."""
        options = {
            "branch": self.branch,
            "depth": self.depth,
        }
        for key in ("repo", "base_dir", "base_url", "dest"):
            value = getattr(self, key)
            if value is not None:
                options[key] = value
        options["commands"] = [command.dump_options() for command in self.commands]
        return options

    def merge_options(self, options: dict, *, context: str = "repo options") -> dict:
        """Validate a repo entry and merge supported fields over its defaults."""
        parsed = self.parse_options(options, context, require_repo=True)
        merged = {}
        for key in self.OPTION_KEYS:
            value = getattr(self, key)
            if value is not None or key in ("branch", "depth"):
                merged[key] = value
        merged.update(parsed)
        merged["commands"] = self.copy_commands(merged["commands"])
        return merged

    @classmethod
    def parse_options(
        cls, options, context: str, *, require_repo: bool = False
    ) -> dict:
        """Validate a raw config object and return unmerged, parsed options.

        Unknown fields are ignored and missing fields remain absent. Explicit
        None values for branch and depth are preserved to clear inherited values.
        Command dictionaries become new RepoCommand objects; path strings and
        leading $dest placeholders are not resolved. The input is not modified.
        Configuration errors carry the supplied context.
        """
        cls.validate_options(options, context, require_repo=require_repo)
        parsed = {}
        for key in cls.OPTION_KEYS:
            if key in options:
                parsed[key] = options[key]
        if "commands" in parsed:
            commands = parsed["commands"]
            if not isinstance(commands, list):
                raise RepoConfigError("commands must be a list", context=context)
            parsed_commands = []
            for index, entry in enumerate(commands):
                location = "{}: commands[{}]".format(context, index)
                parsed_commands.append(
                    RepoCommand.from_options(entry, context=location)
                )
            parsed["commands"] = parsed_commands
        return parsed

    @staticmethod
    def validate_string(value, *, field: str, context: str) -> None:
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            msg = "{} must be a nonempty string"
            raise RepoConfigError(msg.format(field), context=context)

    @staticmethod
    def validate_depth(depth, *, context: str) -> None:
        if depth is not None and (type(depth) is not int or depth <= 0):
            msg = "depth must be a positive integer or null"
            raise RepoConfigError(msg, context=context)

    @classmethod
    def validate_options(
        cls, options, context: str, *, require_repo: bool = False
    ) -> None:
        """Validate non-command fields using the same rules at every layer."""
        if not isinstance(options, dict):
            raise RepoConfigError("options must be an object", context=context)
        if require_repo and "repo" not in options:
            raise RepoConfigError("repo must be a nonempty string", context=context)
        for key in ("repo", "dest", "base_dir", "base_url", "branch"):
            if key not in options:
                continue
            value = options[key]
            if key == "branch" and value is None:
                continue
            cls.validate_string(value, field=key, context=context)
        cls.validate_depth(options.get("depth"), context=context)

    def validate(self) -> None:
        """Validate this spec's attributes without resolving or changing them."""
        for index, command in enumerate(self.commands):
            if not isinstance(command, RepoCommand):
                msg = "commands[{}] must be a RepoCommand"
                raise ValueError(msg.format(index))
            command.validate(context="commands[{}]".format(index))
        if self.repo is not None and self.dest is None:
            raise ValueError("dest must be a nonempty string")
        for key in ("repo", "dest", "base_dir", "base_url", "branch"):
            value = getattr(self, key)
            if value is not None:
                self.validate_string(value, field=key, context="repo options")
        self.validate_depth(self.depth, context="repo options")

    @staticmethod
    def parse_repo(repo: str) -> Tuple[str, SplitResult]:
        """Classify once, preserving the original address and undecoded path."""
        if repo.startswith("file://"):
            address = repo[len("file://") :]
            host, separator, path = address.partition("/")
            if separator:
                path = "/" + path
            # Git treats ? and # as path characters for its file transport.
            return "url", SplitResult("file", host, path, "", "")
        if "://" in repo:
            return "url", urlsplit(repo)
        scp_match = re.match(r"^([^/]+?):(.*)$", repo, re.DOTALL)
        if scp_match is not None:
            ipv6 = re.match(r"^((?:[^/@:]+@)?\[[^\]]+\]):(.*)$", repo, re.DOTALL)
            if ipv6 is not None:
                scp_match = ipv6
            host, path = scp_match.groups()
            return "scp", SplitResult("", host, path, "", "")
        return "path", SplitResult("", "", repo, "", "")

    @staticmethod
    def decode_file_url_path(path: str) -> str:
        """Decode percent escapes once, retaining filesystem bytes losslessly."""
        raw_path = os.fsencode(path)
        decoded_path = unquote_to_bytes(raw_path)
        return os.fsdecode(decoded_path)

    @classmethod
    def is_url(cls, repo: str) -> bool:
        kind, _ = cls.parse_repo(repo)
        return kind != "path"

    @staticmethod
    def expand_path(value: str) -> str:
        return os.path.expanduser(str(value))

    @classmethod
    def absolute_path(cls, value: str, base: str) -> str:
        expanded = cls.expand_path(value)
        path = os.path.join(str(base), expanded)
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        # Keep .. for the filesystem to resolve after traversing symbolic links.
        components = path
        if os.path.altsep is not None:
            components = components.replace(os.path.altsep, os.path.sep)
        if os.path.pardir in components.split(os.path.sep):
            return path
        return os.path.normpath(path)

    @classmethod
    def normalize_dest(cls, value: str, base: str) -> str:
        """Expose the final path entry without collapsing intermediate parents."""
        dest = cls.absolute_path(value, base)
        while True:
            parent, name = os.path.split(dest)
            if name not in ("", os.path.curdir) or parent == dest:
                return dest
            dest = parent

    @classmethod
    def canonical_path(cls, value: str, base: str) -> str:
        expanded = cls.expand_path(value)
        path = os.path.join(str(base), expanded)
        return os.path.realpath(path)

    @staticmethod
    def is_within(path: str, parent: str) -> bool:
        """Compare absolute canonical paths, including equality and filesystem roots."""
        try:
            return os.path.commonpath([path, parent]) == parent
        except ValueError:
            # Paths on different Windows drives have no common ancestor.
            return False

    @classmethod
    def normalize_base_url(cls, value: str, base: str) -> str:
        if cls.is_url(value):
            return value
        return cls.absolute_path(value, base)

    @classmethod
    def resolve_repo(
        cls, repo: str, base: str, *, base_url: Optional[str] = None
    ) -> str:
        kind, _ = cls.parse_repo(repo)
        if kind != "path":
            return repo
        local_path = cls.absolute_path(repo, base)
        is_name = (
            repo not in (".", "..")
            and not repo.startswith("~")
            and "/" not in repo
            and "\\" not in repo
        )
        if base_url is None or not is_name:
            return local_path
        if os.path.exists(local_path):
            return local_path

        prefix_kind, prefix = cls.parse_repo(base_url)
        is_scp_root = prefix_kind == "scp" and not prefix.path
        separator = "/"
        if base_url.endswith("/") or is_scp_root:
            separator = ""
        return base_url + separator + repo

    @classmethod
    def default_dest(cls, repo: str, parent: Optional[str] = None) -> str:
        kind, parsed_repo = cls.parse_repo(repo)
        path = parsed_repo.path.rstrip("/")
        name = path.rsplit("/", 1)[-1]
        if kind == "url" and parsed_repo.scheme == "file":
            name = cls.decode_file_url_path(name)
        elif kind == "url":
            name = unquote(name)
        if name.endswith(".git"):
            name = name[:-4]
        has_separator = "/" in name or "\\" in name or "\0" in name
        if name in ("", ".", "..") or has_separator:
            msg = "cannot infer repo name from {!r}; specify dest explicitly"
            raise ValueError(msg.format(repo))
        if parent is None:
            parent = os.getcwd()
        return os.path.join(str(parent), name)

    @classmethod
    def parse_cli_repo(
        cls, value: str, base: str, *, inline_dest: bool = True
    ) -> Tuple[str, Optional[str], bool]:
        """Identify a config or repo, optionally splitting the CLI => suffix."""
        if not value.strip() or "\0" in value:
            raise ValueError("repo input must be a nonempty URL or path")
        if not cls.is_url(value):
            path = cls.absolute_path(value, base)
            if os.path.isfile(path):
                return path, None, True

        repo, separator, dest = value, "", ""
        if inline_dest:
            repo, separator, dest = value.rpartition("=>")
            if not separator:
                repo = value
        if not repo.strip() or "\0" in repo:
            raise ValueError("repo input must be a nonempty URL or path")
        if not cls.is_url(repo):
            path = cls.absolute_path(repo, base)
            _, extension = os.path.splitext(path)
            missing_json = extension.lower() == ".json" and not os.path.isdir(path)
            if os.path.isfile(path) or missing_json:
                if separator:
                    msg = "{}: set repo dests inside the config, not with =>"
                    raise ValueError(msg.format(repo))
                return path, None, True

        if separator:
            if not dest.strip() or "\0" in dest:
                raise ValueError("dest after => must be a nonempty path")
            return repo, dest, False
        return repo, None, False

    @classmethod
    def command_cwd(cls, value: str, base: str, dest: str) -> str:
        if value.startswith("$dest"):
            value = str(dest) + value[len("$dest") :]
        return cls.absolute_path(value, base)

    @classmethod
    def identity(cls, repo: str, base: str) -> Tuple[str, str]:
        """Compare addresses conservatively; do not equate different transports."""
        kind, parsed_repo = cls.parse_repo(repo)
        if (
            kind == "url"
            and parsed_repo.scheme == "file"
            and parsed_repo.netloc in ("", "localhost")
        ):
            local_path = cls.decode_file_url_path(parsed_repo.path)
            return "local", cls.canonical_path(local_path, os.getcwd())
        if kind != "path":
            address = repo.rstrip("/")
            if address.endswith(".git"):
                address = address[:-4]
            return "remote", address
        return "local", cls.canonical_path(repo, base)


class GitNotFoundError(RuntimeError):
    pass


class RepoBatchInstallError(RuntimeError):
    def __init__(self, failures: Sequence[Tuple[RepoSpec, Exception]]) -> None:
        self.failures = list(failures)
        details = [
            "{} -> {}: {}".format(spec.repo, spec.dest, error)
            for spec, error in self.failures
        ]
        summary = "\n".join(details)
        msg = "{} repos failed:\n{}".format(len(details), summary)
        super().__init__(msg)


class SingleValueAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            parser.error("{} may only be specified once".format(option_string))
        setattr(namespace, self.dest, values)


class CommandRunner:
    """Execute commands and Git while preserving the caller's environment."""

    @staticmethod
    def format_command(command: Sequence[str]) -> str:
        return " ".join(shlex.quote(str(argument)) for argument in command)

    @staticmethod
    def run_command(
        command: Sequence[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False
    ) -> subprocess.CompletedProcess:
        """Run without a shell, merging env overrides into the current environment."""
        environment = os.environ.copy()
        if env is not None:
            environment.update(env)
        if cwd is not None:
            cwd = str(cwd)
        command = [str(argument) for argument in command]
        output = None
        if capture_output:
            output = subprocess.PIPE
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            check=check,
            stdout=output,
            stderr=output,
            universal_newlines=text,
        )

    @classmethod
    def run_git(
        cls,
        *arguments: str,
        cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False
    ) -> subprocess.CompletedProcess:
        try:
            return cls.run_command(
                ["git", *arguments],
                cwd=cwd,
                env=env,
                check=check,
                capture_output=capture_output,
                text=text,
            )
        except FileNotFoundError as exc:
            # Python 3.5 subprocess exceptions do not populate filename.
            if exc.filename not in (None, "git"):
                raise
            if exc.filename is None and cwd is not None:
                if not os.path.isdir(str(cwd)):
                    raise
            msg = "git executable not found; install Git and check PATH"
            raise GitNotFoundError(msg) from exc

    @classmethod
    def read_git_value(
        cls,
        *arguments: str,
        cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None
    ) -> Optional[str]:
        """Read a Git value, removing only its appended terminating newline."""
        result = cls.run_git(
            *arguments,
            cwd=cwd,
            env=env,
            capture_output=True,
        )
        if result.returncode:
            return None
        # Text mode would translate CR and CRLF inside paths and config values.
        value = os.fsdecode(result.stdout)
        if value.endswith("\n"):
            value = value[:-1]
        return value

    @classmethod
    def read_git_config_values(
        cls,
        key: str,
        *,
        cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None
    ) -> List[str]:
        """Read raw config values in order, preserving whitespace within each."""
        result = cls.run_git(
            "config",
            "--null",
            "--get-all",
            key,
            cwd=cwd,
            env=env,
            capture_output=True,
        )
        if result.returncode:
            return []
        values = result.stdout.split(b"\0")[:-1]
        return [os.fsdecode(value) for value in values]


class RepoFile(RepoSpec):
    """Recursively load config files using each node's effective options."""

    def __init__(
        self,
        repo_file: Optional[str] = None,
        *,
        cwd: Optional[str] = None,
        base_dir: Optional[str] = None,
        base_url: Optional[str] = None,
        branch: Optional[str] = None,
        depth: Optional[int] = None,
        dest: Optional[str] = None,
        commands: Optional[Sequence[RepoCommand]] = None
    ) -> None:
        if cwd is None:
            self.cwd = os.getcwd()
        else:
            self.cwd = RepoSpec.absolute_path(cwd, os.getcwd())
        if base_dir is not None:
            base_dir = str(base_dir)
        self.repo_file = repo_file
        self.entries = []
        super().__init__(
            dest=dest,
            base_dir=base_dir,
            base_url=base_url,
            branch=branch,
            depth=depth,
            commands=commands,
        )

    @property
    def input_dir(self) -> str:
        if self.repo_file is None:
            return self.cwd
        return os.path.dirname(self.repo_file)

    @property
    def repo_specs(self) -> List[RepoSpec]:
        return [entry for entry in self.entries if not isinstance(entry, RepoFile)]

    @property
    def repo_files(self) -> List["RepoFile"]:
        return [entry for entry in self.entries if isinstance(entry, RepoFile)]

    def iter_specs(self) -> Iterator[RepoSpec]:
        """Yield all specs recursively in their original input order."""
        for entry in self.entries:
            if isinstance(entry, RepoFile):
                yield from entry.iter_specs()
            else:
                yield entry

    def load_config(self, filename: str) -> dict:
        """Read JSON and check the file structure without resolving options."""
        filename = RepoSpec.absolute_path(filename, self.cwd)
        try:
            with open(filename, encoding="utf-8") as stream:
                config = json.load(stream)
        except (OSError, ValueError) as exc:
            msg = "cannot read JSON config: {}"
            raise RepoConfigError(msg.format(exc), context=filename) from exc
        if not isinstance(config, dict):
            raise RepoConfigError("config must be an object", context=filename)
        if not isinstance(config.get("repos", []), list):
            raise RepoConfigError("repos must be a list", context=filename)
        return config

    def normalize_bases(self) -> None:
        """Resolve the current base_dir and base_url paths."""
        base_dir = self.base_dir
        if base_dir is None:
            base_dir = self.cwd
        self.base_dir, self.base_url = self.resolve_bases(
            base_dir,
            self.base_url,
            input_dir=self.cwd,
        )

    @classmethod
    def resolve_bases(
        cls, base_dir: Optional[str], base_url: Optional[str], *, input_dir: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve supplied bases against their explicit declaration directory."""
        if base_dir is not None:
            base_dir = cls.absolute_path(base_dir, input_dir)
        if base_url is not None:
            base_url = cls.normalize_base_url(base_url, input_dir)
        return base_dir, base_url

    def resolve_options(self, options: dict) -> dict:
        """Resolve parsed option paths against this file's input_dir.

        Input commands must already be RepoCommand objects. Present base_dir,
        local base_url and non-$dest command cwd values become absolute paths;
        URL and SCP prefixes are preserved. Repo and dest are passed through
        unchanged, and leading $dest placeholders remain for resolve_spec.
        Return a new dictionary with new command objects, leaving input options
        and inherited commands unchanged.
        """
        resolved = dict(options)
        base_dir, base_url = self.resolve_bases(
            options.get("base_dir"),
            options.get("base_url"),
            input_dir=self.input_dir,
        )
        if "base_dir" in options:
            resolved["base_dir"] = base_dir
        if "base_url" in options:
            resolved["base_url"] = base_url
        if "commands" in resolved:
            commands = []
            for entry in resolved["commands"]:
                cwd = entry.cwd
                if not cwd.startswith("$dest"):
                    cwd = self.absolute_path(cwd, self.input_dir)
                commands.append(RepoCommand(entry.cmd, cwd))
            resolved["commands"] = commands
        return resolved

    def resolve_spec(
        self,
        repo: str,
        *,
        base_dir: str,
        base_url: Optional[str] = None,
        dest: Optional[str] = None,
        branch: Optional[str] = None,
        depth: Optional[int] = None,
        commands: Sequence[RepoCommand] = ()
    ) -> RepoSpec:
        """Build a final spec from effective options with prepared base paths.

        base_dir and any local base_url must already be absolute. Command cwd
        values must be anchored at their declaration directory or start with
        $dest, as prepared by resolve_options. Resolve the repo name or local
        path, infer a missing dest and expand command $dest placeholders.
        The result has absolute local repo, dest and command cwd paths; URL and
        SCP addresses remain unchanged. Input command objects are not modified.
        """
        repo = self.resolve_repo(repo, self.input_dir, base_url=base_url)
        if dest is None:
            dest = self.default_dest(repo, base_dir)
        dest = self.normalize_dest(dest, base_dir)
        command_dest = self.canonical_path(dest, self.input_dir)
        resolved_commands = []
        for command in commands:
            cwd = command.cwd
            cwd = self.command_cwd(cwd, self.input_dir, command_dest)
            resolved_commands.append(RepoCommand(command.cmd, cwd))
        return RepoSpec(
            repo,
            dest,
            branch,
            depth,
            commands=resolved_commands,
            base_dir=base_dir,
            base_url=base_url,
        )

    def parse_entry(
        self, options: Union[str, dict], *, context: str
    ) -> Tuple[dict, bool]:
        """Parse and resolve one input, preserving its config-file classification."""
        is_config = None
        if isinstance(options, str):
            repo, dest, is_config = self.parse_cli_repo(options, self.input_dir)
            options = {"repo": repo}
            if dest is not None:
                options["dest"] = dest
        merged_options = self.merge_options(options, context=context)
        resolved_options = self.resolve_options(merged_options)
        repo = resolved_options["repo"]
        if is_config is None:
            repo, _, is_config = self.parse_cli_repo(
                repo, self.input_dir, inline_dest=False
            )
        resolved_options["repo"] = repo
        return resolved_options, is_config

    def load_entry(
        self, options: Union[str, dict], *, active_files: Sequence[str], context: str
    ) -> Union[RepoSpec, "RepoFile"]:
        """Create a final spec or recursively load a child file from one input."""
        resolved_options, is_config = self.parse_entry(options, context=context)
        repo = resolved_options["repo"]
        if is_config:
            child = RepoFile(
                repo,
                cwd=self.cwd,
                dest=resolved_options.get("dest"),
                base_dir=resolved_options["base_dir"],
                base_url=resolved_options.get("base_url"),
                branch=resolved_options.get("branch"),
                depth=resolved_options.get("depth"),
                commands=resolved_options.get("commands", []),
            )
            child.load_from_file(active_files=active_files)
            return child
        return self.resolve_spec(
            repo,
            dest=resolved_options.get("dest"),
            base_dir=resolved_options["base_dir"],
            base_url=resolved_options.get("base_url"),
            branch=resolved_options.get("branch"),
            depth=resolved_options.get("depth"),
            commands=resolved_options.get("commands", []),
        )

    def add_repo(
        self,
        options: Union[str, dict],
        *,
        active_files: Sequence[str] = (),
        context: Optional[str] = None
    ) -> None:
        """Load, check and append one entry, attaching its location on failure."""
        if context is None:
            context = self.repo_file
            if context is None:
                context = "command line"
        try:
            entry = self.load_entry(options, active_files=active_files, context=context)
            if isinstance(entry, RepoFile):
                new_specs = entry.iter_specs()
            else:
                new_specs = [entry]
            self.check_dest_conflicts(new_specs)
        except RepoConfigError:
            raise
        except ValueError as exc:
            raise RepoConfigError(str(exc), context=context) from exc
        self.entries.append(entry)

    def load_defaults(self, options: dict) -> None:
        """Apply this file's defaults, attaching their location on failure."""
        context = "{}: defaults".format(self.repo_file)
        try:
            parsed = self.parse_options(options, context)
            resolved = self.resolve_options(parsed)
            self.apply_options(resolved)
        except RepoConfigError:
            raise
        except ValueError as exc:
            raise RepoConfigError(str(exc), context=context) from exc

    def check_dest_conflicts(self, specs: Iterable[RepoSpec]) -> None:
        """Reject conflicts within new specs or with any previously loaded spec."""
        dests = []
        for previous_spec in self.iter_specs():
            dests.append(self.canonical_path(previous_spec.dest, self.cwd))
        for new_spec in specs:
            resolved = self.canonical_path(new_spec.dest, self.cwd)
            for previous in dests:
                inside_previous = self.is_within(resolved, previous)
                contains_previous = self.is_within(previous, resolved)
                if inside_previous or contains_previous:
                    msg = "conflicting dests: {} and {}"
                    raise ValueError(msg.format(previous, resolved))
            dests.append(resolved)

    def load_from_cmd(self, inputs: Sequence[str]) -> "RepoFile":
        """Set up the CLI root and process its inputs one at a time."""
        if not inputs:
            filename = os.path.join(self.cwd, DEFAULT_REPO_FILENAME)
            if not os.path.isfile(filename):
                msg = "default config file not found or not a regular file: {}"
                raise ValueError(msg.format(filename))
            inputs = [filename]
        self.repo_file = None
        self.entries = []
        self.normalize_bases()
        for index, value in enumerate(inputs, 1):
            context = "command line: repo argument {}".format(index)
            self.add_repo(value, context=context)
        return self

    def load_from_file(self, *, active_files: Sequence[str] = ()) -> "RepoFile":
        """Read this file, override inherited options and load its repos in order."""
        if self.repo_file is None:
            raise ValueError("repo_file is required to load a file")
        self.repo_file = RepoSpec.absolute_path(self.repo_file, self.cwd)
        canonical = RepoSpec.canonical_path(self.repo_file, self.cwd)
        if canonical in active_files:
            raise RepoConfigError("circular config reference", context=self.repo_file)
        active_files = tuple(active_files) + (canonical,)
        self.entries = []
        config = self.load_config(self.repo_file)
        self.normalize_bases()
        self.load_defaults(config.get("defaults", {}))
        for index, entry in enumerate(config.get("repos", [])):
            context = "{}: repos[{}]".format(self.repo_file, index)
            self.add_repo(entry, active_files=active_files, context=context)
        return self


class RepoInstaller:
    """Install resolved specs through a shared command runner."""

    def __init__(self, *, runner: Optional[CommandRunner] = None) -> None:
        if runner is None:
            runner = CommandRunner()
        self.runner = runner

    def install_specs(
        self,
        specs: Iterable[RepoSpec],
        *,
        force: bool = False,
        dry_run: bool = False,
        run_commands: bool = True
    ) -> None:
        """Attempt every spec, then raise all installation failures together."""
        failures = []
        for spec in specs:
            commands = None
            if run_commands:
                commands = spec.commands
            try:
                self.install(
                    spec.repo,
                    spec.dest,
                    branch=spec.branch,
                    depth=spec.depth,
                    force=force,
                    dry_run=dry_run,
                    commands=commands,
                )
            except (
                OSError,
                RuntimeError,
                ValueError,
                subprocess.CalledProcessError,
            ) as exc:
                failures.append((spec, exc))
        if failures:
            raise RepoBatchInstallError(failures)

    def matches_dest(self, dest: str, repo: str) -> bool:
        if not os.path.isdir(dest):
            return False
        # This must be a working tree root, not a directory inside another repo.
        root_path = self.runner.read_git_value(
            "-C",
            str(dest),
            "rev-parse",
            "--show-toplevel",
        )
        if root_path is None:
            return False
        cwd = os.getcwd()
        root_path = RepoSpec.canonical_path(root_path, cwd)
        dest_path = RepoSpec.canonical_path(dest, cwd)
        if root_path != dest_path:
            return False
        origin_urls = self.runner.read_git_config_values("remote.origin.url", cwd=dest)
        origin_url = None
        for value in origin_urls:
            # Git uses the first URL after the last empty-value reset.
            if value == "":
                origin_url = None
            elif origin_url is None:
                origin_url = value
        if origin_url is None:
            return False
        origin_identity = RepoSpec.identity(origin_url, dest)
        requested_identity = RepoSpec.identity(repo, cwd)
        return origin_identity == requested_identity

    @staticmethod
    def clone_command(
        repo: str,
        dest: str,
        *,
        branch: Optional[str] = None,
        depth: Optional[int] = None
    ) -> List[str]:
        command = ["git", "clone"]
        for option, value in (
            ("--branch", branch),
            ("--depth", depth),
        ):
            if value is not None:
                command.extend([option, str(value)])
        command.extend(["--", repo, str(dest)])
        return command

    def clone(
        self,
        repo: str,
        dest: str,
        *,
        branch: Optional[str] = None,
        depth: Optional[int] = None,
        commands: Optional[Sequence[RepoCommand]] = None
    ) -> None:
        git_command = self.clone_command(repo, dest, branch=branch, depth=depth)
        display_command = self.runner.format_command(git_command)
        print(display_command, flush=True)
        self.runner.run_git(*git_command[1:], check=True)
        if commands is not None:
            self.execute_commands(commands)

    @staticmethod
    def check_replace_dest(dest: str) -> None:
        cwd = os.getcwd()
        dest = RepoSpec.normalize_dest(dest, cwd)
        if os.path.islink(dest):
            raise RuntimeError("refusing to replace a symbolic link: {}".format(dest))
        resolved = RepoSpec.canonical_path(dest, cwd)
        home = RepoSpec.canonical_path("~", cwd)
        working_dir = RepoSpec.canonical_path(cwd, cwd)
        script_path = RepoSpec.canonical_path(__file__, cwd)
        script_dir = os.path.dirname(script_path)
        msg = "refusing to replace a protected directory: {}"
        if resolved == home:
            raise RuntimeError(msg.format(dest))
        for path in (working_dir, script_dir):
            if RepoSpec.is_within(path, resolved):
                raise RuntimeError(msg.format(dest))

    @staticmethod
    def publish_replacement(replacement: str, dest: str, backup: str) -> None:
        """Publish the clone, restoring the previous dest if publication fails."""
        os.rename(dest, backup)
        try:
            os.rename(replacement, dest)
        except BaseException as exc:
            try:
                os.rename(backup, dest)
            except OSError as recovery_error:
                if not isinstance(exc, Exception):
                    raise exc from recovery_error
                msg = (
                    "replacement failed: {}; restoration failed: {}; "
                    "original dest retained at {}"
                ).format(exc, recovery_error, backup)
                raise RuntimeError(msg) from recovery_error
            raise

    @staticmethod
    def cleanup_staging(
        staging: str,
        backup: str,
        *,
        installed: bool,
        pending_error: Optional[BaseException] = None
    ) -> None:
        """Retain unrestored backups and avoid masking an active exception."""
        if os.path.exists(backup) and not installed:
            print("error: original dest retained at {}".format(backup), file=sys.stderr)
            return
        try:
            shutil.rmtree(staging)
        except OSError as cleanup_error:
            msg = "error: could not remove temporary directory {}: {}"
            print(msg.format(staging, cleanup_error), file=sys.stderr)
            if pending_error is None:
                raise

    def replace(
        self,
        repo: str,
        dest: str,
        *,
        branch: Optional[str] = None,
        depth: Optional[int] = None,
        commands: Optional[Sequence[RepoCommand]] = None
    ) -> None:
        # Keep the old dest until cloning succeeds. Sibling staging keeps
        # renames on the same filesystem, and permits rollback if publication fails.
        self.check_replace_dest(dest)
        # Freeze the path before moving a dest that may contain its own aliases.
        dest = RepoSpec.canonical_path(dest, os.getcwd())
        parent = os.path.dirname(dest)
        staging = tempfile.mkdtemp(prefix=".repo-console-", dir=parent)
        replacement = os.path.join(staging, "new")
        backup = os.path.join(staging, "previous")
        installed = False
        try:
            self.clone(repo, replacement, branch=branch, depth=depth)
            self.publish_replacement(replacement, dest, backup)
            installed = True
            print("Replaced: {}".format(dest), flush=True)
        finally:
            pending_error = sys.exc_info()[1]
            self.cleanup_staging(
                staging,
                backup,
                installed=installed,
                pending_error=pending_error,
            )
        # Initialization failures must not enter the replacement rollback/cleanup.
        if commands is not None:
            self.execute_commands(commands)

    def execute_commands(
        self, commands: Sequence[RepoCommand], *, dry_run: bool = False
    ) -> None:
        for entry in commands:
            display_cwd = shlex.quote(str(entry.cwd))
            msg = "Command (cwd={}): {}".format(display_cwd, entry.cmd)
            print(msg, flush=True)
            if not dry_run:
                self.runner.run_command(
                    ["bash", "-c", entry.cmd], cwd=entry.cwd, check=True
                )

    def install(
        self,
        repo: str,
        dest: str,
        *,
        branch: Optional[str] = None,
        depth: Optional[int] = None,
        force: bool = False,
        dry_run: bool = False,
        commands: Optional[Sequence[RepoCommand]] = None
    ) -> None:
        dest = RepoSpec.normalize_dest(dest, os.getcwd())
        exists = os.path.lexists(dest)
        if exists and self.matches_dest(dest, repo):
            print("Already installed; skipping: {}".format(dest))
            return
        if exists:
            if not force:
                msg = (
                    "dest is not the requested repo: {}; "
                    "use --force to replace its contents"
                )
                raise RuntimeError(msg.format(dest))
            self.check_replace_dest(dest)
        if dry_run:
            if exists:
                msg = "Would clone into a temporary directory, then replace: {}"
                print(msg.format(dest))
            git_command = self.clone_command(repo, dest, branch=branch, depth=depth)
            display_command = self.runner.format_command(git_command)
            print(display_command, flush=True)
            if commands is not None:
                self.execute_commands(commands, dry_run=True)
            return
        if exists:
            self.replace(repo, dest, branch=branch, depth=depth, commands=commands)
        else:
            self.clone(repo, dest, branch=branch, depth=depth, commands=commands)


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def repo_install(
    inputs: Sequence[str],
    *,
    base_dir: Optional[str] = None,
    base_url: Optional[str] = None,
    branch: Optional[str] = None,
    depth: Optional[int] = None,
    force: bool = False,
    dry_run: bool = False,
    run_commands: bool = True
) -> None:
    """Resolve inputs and install repos, optionally running their commands."""
    repo_file = RepoFile(
        base_dir=base_dir,
        base_url=base_url,
        branch=branch,
        depth=depth,
    )
    repo_file.load_from_cmd(inputs)
    installer = RepoInstaller()
    installer.install_specs(
        repo_file.iter_specs(),
        force=force,
        dry_run=dry_run,
        run_commands=run_commands,
    )


def cmd_install(args: argparse.Namespace) -> None:
    repo_install(
        args.repos,
        base_dir=args.base_dir,
        base_url=args.base_url,
        branch=args.branch,
        depth=args.depth,
        force=args.force,
        dry_run=args.dry_run,
        run_commands=args.run_commands,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clone Git repos and optionally run configured commands."
    )
    parser.set_defaults(func=None)
    commands = parser.add_subparsers(dest="command")
    repo_inputs = argparse.ArgumentParser(add_help=False)
    repo_inputs.add_argument(
        "repos",
        nargs="*",
        help="URL/name[=>path], local repo[=>path] or JSON config file; defaults to ./repo-console.json",
    )
    repo_options = argparse.ArgumentParser(add_help=False, parents=[repo_inputs])
    repo_options.add_argument(
        "-bd",
        "--base-dir",
        action=SingleValueAction,
        help="parent directory inherited by configs (default: current directory)",
    )
    repo_options.add_argument(
        "-bu",
        "--base-url",
        action=SingleValueAction,
        help="repo name prefix inherited by configs",
    )
    repo_options.add_argument("-b", "--branch", help="branch or tag to check out")
    repo_options.add_argument(
        "-d", "--depth", type=positive_int, help="shallow clone history depth"
    )
    repo_options.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="replace a dest that is not the requested repo",
    )
    repo_options.add_argument(
        "-dr",
        "--dry-run",
        action="store_true",
        help="inspect and print the plan without changes",
    )
    prepare = commands.add_parser(
        "prepare",
        aliases=["p"],
        parents=[repo_options],
        help="clone repos without running configured commands",
    )
    prepare.set_defaults(func=cmd_install, run_commands=False)
    install = commands.add_parser(
        "install",
        aliases=["i"],
        parents=[repo_options],
        help="clone repos and run configured commands",
    )
    install.set_defaults(func=cmd_install, run_commands=True)
    args, extra_inputs = parser.parse_known_args()
    if extra_inputs:
        # Python 3.5 argparse leaves repos after interspersed options unparsed.
        # Parse those as positionals, preserving -- and rejecting unknown options.
        remaining, unknown = repo_inputs.parse_known_args(extra_inputs)
        if unknown:
            parser.error("unrecognized arguments: {}".format(" ".join(unknown)))
        args.repos.extend(remaining.repos)
    if args.func is None:
        parser.print_help()
        return 0
    try:
        args.func(args)
        return 0
    except RepoBatchInstallError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        first_error = exc.failures[0][1]
        if isinstance(first_error, GitNotFoundError):
            return 127
        if isinstance(first_error, subprocess.CalledProcessError):
            code = first_error.returncode
            if code < 0:
                return 128 - code
            return code
        return 1
    except GitNotFoundError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 127
    except ValueError as exc:
        parser.error(str(exc))
    except (OSError, RuntimeError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nerror: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
