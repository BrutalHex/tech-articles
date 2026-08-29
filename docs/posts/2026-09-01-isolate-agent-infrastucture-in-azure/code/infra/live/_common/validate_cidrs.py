from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from pathlib import Path

ASSIGN_RE = re.compile(
    r'^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"(?P<cidr>\d+\.\d+\.\d+\.\d+/\d+)"'
)
BLOCK_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{")
QUOTED_BLOCK_RE = re.compile(r'^"(?P<key>[^"]+)"\s*=\s*\{')
LIST_ITEM_RE = re.compile(r'^"(?P<cidr>\d+\.\d+\.\d+\.\d+/\d+)"\s*,?\s*$')

HUB_CHILD_KEYS = {
    "gateway",
    "firewall",
    "management",
    "dns_in",
    "dns_out",
    "spare",
    "tgw",
    "vpn",
}


class Cidr:
    def __init__(self, raw: str, path: str, line: int):
        self.raw = raw
        self.path = path
        self.line = line
        try:
            self.net = ipaddress.ip_network(raw, strict=False)
        except ValueError as exc:
            raise SystemExit(f"{path}:{line}: invalid CIDR {raw!r} ({exc})") from exc
        self.aligned = ipaddress.ip_network(raw, strict=False).network_address == ipaddress.ip_interface(raw).ip

    def overlaps(self, other: "Cidr") -> bool:
        return self.net.overlaps(other.net)

    def contains(self, other: "Cidr") -> bool:
        return other.net.subnet_of(self.net)

    def __str__(self) -> str:
        return f"{self.raw} ({self.path}:{self.line})"


def parse_plan(text: str) -> list[Cidr]:
    cidrs: list[Cidr] = []
    stack: list[str] = []
    pending_list: str | None = None

    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if pending_list:
            if line.startswith("]"):
                pending_list = None
                continue
            item = LIST_ITEM_RE.match(line)
            if item:
                path = f"{'.'.join(stack)}.{pending_list}" if stack else pending_list
                cidrs.append(Cidr(item.group("cidr"), path, lineno))
            continue

        if line == "}":
            if stack:
                stack.pop()
            continue

        block = BLOCK_RE.match(line) or QUOTED_BLOCK_RE.match(line)
        if block:
            stack.append(block.group("key"))
            continue

        listed = re.match(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*\[", line)
        if listed:
            pending_list = listed.group("key")
            continue

        assigned = ASSIGN_RE.match(line)
        if assigned:
            path = ".".join(stack + [assigned.group("key")])
            cidrs.append(Cidr(assigned.group("cidr"), path, lineno))

    return cidrs


def by_prefix(cidrs: list[Cidr], prefix: str) -> list[Cidr]:
    return [c for c in cidrs if c.path == prefix or c.path.startswith(prefix + ".")]


def one(cidrs: list[Cidr], path: str) -> Cidr:
    matches = [c for c in cidrs if c.path == path]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one CIDR at {path}, found {len(matches)}")
    return matches[0]


def validate(cidrs: list[Cidr]) -> list[str]:
    errors: list[str] = []

    azure_super = one(cidrs, "supernets.azure")
    aws_super = one(cidrs, "supernets.aws")

    if azure_super.overlaps(aws_super):
        errors.append(f"supernets overlap: {azure_super} vs {aws_super}")

    azure_allocs = [
        c for c in by_prefix(cidrs, "azure") if not c.path.startswith("vpn_advertised")
    ]
    aws_allocs = [
        c for c in by_prefix(cidrs, "aws") if not c.path.startswith("vpn_advertised")
    ]

    def cloud_membership(allocs: list[Cidr], own: Cidr, other: Cidr, own_name: str, other_name: str) -> None:
        for c in allocs:
            if not own.contains(c):
                errors.append(f"{c} is not inside the {own_name} supernet {own.raw}")
            if other.contains(c) or c.overlaps(other):
                errors.append(f"{c} belongs in {own_name} but collides with the {other_name} supernet {other.raw}")

    cloud_membership(azure_allocs, azure_super, aws_super, "Azure", "AWS")
    cloud_membership(aws_allocs, aws_super, azure_super, "AWS", "Azure")

    for a in azure_allocs:
        for b in aws_allocs:
            if a.overlaps(b):
                errors.append(f"cross-cloud overlap: {a} vs {b}")

    def hub_and_siblings(cloud: str) -> list[Cidr]:
        roots: list[Cidr] = []
        for c in cidrs:
            parts = c.path.split(".")
            if parts[0] != cloud:
                continue
            if c.path.endswith(".hub.cidr") or c.path.endswith(".spoke_platform"):
                roots.append(c)
                continue
            if ".hub." in c.path:
                parent_path = ".".join(parts[: parts.index("hub") + 1]) + ".cidr"
                parent = next((p for p in cidrs if p.path == parent_path), None)
                if parent is None:
                    errors.append(f"{c} has no parent hub cidr at {parent_path}")
                    continue
                if not parent.contains(c):
                    errors.append(f"{c} is not contained in hub {parent}")
        return roots

    roots = hub_and_siblings("azure") + hub_and_siblings("aws")
    for i, a in enumerate(roots):
        for b in roots[i + 1 :]:
            if a.overlaps(b):
                errors.append(f"allocation overlap: {a} vs {b}")

    reserved = by_prefix(cidrs, "reserved_other")
    owned = azure_allocs + aws_allocs
    for r in reserved:
        for c in owned:
            if r.overlaps(c):
                errors.append(f"allocation {c} overlaps reserved range {r}")

    def advertised(plane: str, direction: str) -> list[Cidr]:
        return [c for c in cidrs if c.path == f"vpn_advertised.{plane}.{direction}"]

    for plane in ("prod", "nonprod"):
        for adv in advertised(plane, "azure_to_aws"):
            if not azure_super.contains(adv):
                errors.append(f"{adv} advertised Azure→AWS but is outside the Azure supernet")
            if aws_super.contains(adv) or adv.overlaps(aws_super):
                errors.append(f"{adv} advertised Azure→AWS but collides with the AWS supernet")
        for adv in advertised(plane, "aws_to_azure"):
            if not aws_super.contains(adv):
                errors.append(f"{adv} advertised AWS→Azure but is outside the AWS supernet")
            if azure_super.contains(adv) or adv.overlaps(azure_super):
                errors.append(f"{adv} advertised AWS→Azure but collides with the Azure supernet")

    for direction in ("azure_to_aws", "aws_to_azure"):
        prod = advertised("prod", direction)
        nonprod = advertised("nonprod", direction)
        for a in prod:
            for b in nonprod:
                if a.overlaps(b):
                    errors.append(f"VPN planes leak into each other ({direction}): {a} vs {b}")

    return errors


def assert_unit_cidr(cidrs: list[Cidr], cloud: str, raw: str) -> list[str]:
    errors: list[str] = []
    candidate = Cidr(raw, f"unit.{cloud}", 0)
    azure_super = one(cidrs, "supernets.azure")
    aws_super = one(cidrs, "supernets.aws")
    own = azure_super if cloud == "azure" else aws_super
    other = aws_super if cloud == "azure" else azure_super
    other_name = "AWS" if cloud == "azure" else "Azure"
    if not own.contains(candidate):
        errors.append(f"{raw} is not inside the {cloud} supernet {own.raw}")
    if other.contains(candidate) or candidate.overlaps(other):
        errors.append(f"{raw} cannot be used on {cloud}; it collides with the {other_name} supernet {other.raw}")
    return errors


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, default=here / "cidr-plan.hcl")
    parser.add_argument("--assert-cloud", choices=("aws", "azure"))
    parser.add_argument("--cidr")
    args = parser.parse_args()

    if bool(args.assert_cloud) != bool(args.cidr):
        parser.error("--assert-cloud and --cidr must be used together")

    if not args.plan.is_file():
        print(f"plan not found: {args.plan}", file=sys.stderr)
        return 2

    cidrs = parse_plan(args.plan.read_text())
    errors = validate(cidrs)
    if args.assert_cloud and args.cidr:
        errors.extend(assert_unit_cidr(cidrs, args.assert_cloud, args.cidr))

    if errors:
        print(f"cidr-plan validation failed ({len(errors)} error(s)):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"cidr-plan ok: {len(cidrs)} prefixes in {args.plan}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
