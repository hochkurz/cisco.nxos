#
# (c) 2016 Red Hat Inc.
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
#
from __future__ import absolute_import, division, print_function


__metaclass__ = type

import json
import re

from ansible.errors import AnsibleConnectionFailure
from ansible.module_utils._text import to_bytes, to_text
from ansible_collections.ansible.netcommon.plugins.plugin_utils.terminal_base import TerminalBase


class TerminalModule(TerminalBase):
    terminal_stdout_re = [
        re.compile(
            rb"[\r\n](?!\s*<)?(\x1b\S+)*[a-zA-Z_0-9]{1}[a-zA-Z0-9-_.]*[>|#](?:\s*)(\x1b\S+)*$",
        ),
        re.compile(rb"[\r\n]?[a-zA-Z0-9]{1}[a-zA-Z0-9-_.]*\(.+\)#(?:\s*)$"),
    ]

    terminal_stderr_re = [
        re.compile(rb"% ?Error"),
        re.compile(rb"\nerror:(.*)", re.I),
        re.compile(rb"^% \w+", re.M),
        re.compile(rb"% ?Bad secret"),
        re.compile(rb"invalid input", re.I),
        re.compile(rb"(?:incomplete|ambiguous) command", re.I),
        re.compile(rb"connection timed out", re.I),
        re.compile(rb"[^\r\n] not found", re.I),
        re.compile(rb"'[^']' +returned error code: ?\d+"),
        re.compile(rb"syntax error"),
        re.compile(rb"unknown command"),
        re.compile(rb"user not present"),
        re.compile(rb"invalid (.+?)at '\^' marker", re.I),
        re.compile(rb"configuration not allowed .+ at '\^' marker"),
        re.compile(
            rb"[B|b]aud rate of console should be.* (\d*) to increase [a-z]* level",
            re.I,
        ),
        re.compile(rb"cannot apply non-existing acl policy to interface", re.I),
        re.compile(rb"Duplicate sequence number", re.I),
        re.compile(
            rb"Cannot apply ACL to an interface that is a port-channel member",
            re.I,
        ),
        re.compile(rb"No corresponding (.+) configured", re.I),
        re.compile(rb"(.+)please specify sequence number", re.I),
        re.compile(rb"(.+sufficient free entries are not available in tcam bank.*)", re.I),
    ]

    terminal_config_prompt = re.compile(r"^.*\((?!maint-mode).*\)#$")

    def on_become(self, passwd=None):
        if self._get_prompt().strip().endswith(b"#"):
            return

        out = self._exec_cli_command("show privilege")
        out = to_text(out, errors="surrogate_then_replace").strip()

        # if already at privilege level 15 return
        if "15" in out:
            return

        if self.validate_user_role():
            return

        if "Disabled" in out:
            raise AnsibleConnectionFailure("Feature privilege is not enabled")

        cmd = {"command": "enable"}
        if passwd:
            cmd["prompt"] = to_text(r"(?i)[\r\n]?Password: $", errors="surrogate_or_strict")
            cmd["answer"] = passwd
            cmd["prompt_retry_check"] = True

        try:
            self._exec_cli_command(to_bytes(json.dumps(cmd), errors="surrogate_or_strict"))
            prompt = self._get_prompt()
            if prompt is None or not prompt.strip().endswith(b"enable#"):
                raise AnsibleConnectionFailure(
                    "failed to elevate privilege to enable mode still at prompt [%s]" % prompt,
                )
        except AnsibleConnectionFailure as e:
            prompt = self._get_prompt()
            raise AnsibleConnectionFailure(
                "unable to elevate privilege to enable mode, at prompt [%s] with error: %s"
                % (prompt, e.message),
            )

    def on_unbecome(self):
        prompt = self._get_prompt()
        if prompt is None:
            # if prompt is None most likely the terminal is hung up at a prompt
            return

        if b"(config" in prompt:
            self._exec_cli_command("end")
            self._exec_cli_command("exit")

        elif prompt.endswith(b"enable#"):
            self._exec_cli_command("exit")

    def on_open_shell(self):
        try:
            for cmd in ("terminal length 0", "terminal width 511"):
                self._exec_cli_command(cmd)
        except AnsibleConnectionFailure:
            raise AnsibleConnectionFailure("unable to set terminal parameters")

    def validate_user_role(self):
        user = self._connection._play_context.remote_user

        out = self._exec_cli_command("show user-account %s" % user)
        out = to_text(out, errors="surrogate_then_replace").strip()

        match = re.search(r"roles:(.+)$", out, re.M)
        if match:
            roles = match.group(1).split()
            if "network-admin" in roles:
                return True
            return False
