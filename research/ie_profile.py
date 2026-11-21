"""Versioned fingerprints from the IE metadata emitted by the sniffer."""

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import re


VERSION = 'ie-id-length-v1'
MAX_WIRE_ELEMENTS = 24
IE_NAMES = {
    0: 'SSID',
    1: 'Supported Rates',
    3: 'DS Parameter Set',
    45: 'HT Capabilities',
    50: 'Extended Supported Rates',
    84: 'SSID List',
    127: 'Extended Capabilities',
    191: 'VHT Capabilities',
    221: 'Vendor Specific',
    255: 'Element ID Extension',
}
# The extension subtype is unavailable. It can describe a Short SSID List.
PRIVATE_OR_AMBIGUOUS_IDS = frozenset({0, 84, 255})
TOKEN = re.compile(r'([0-9]{1,3}):([0-9]{1,3})')


@dataclass(frozen=True)
class IEProfile:
    status: str
    elements: tuple[tuple[int, int], ...] = ()
    excluded_ids: tuple[int, ...] = ()
    possibly_truncated: bool = False
    issues: tuple[str, ...] = ()

    @property
    def signature(self):
        if self.status != 'usable':
            return ''
        return ','.join(f'{element_id}:{length}' for element_id, length in self.elements)

    @property
    def fingerprint_hash(self):
        signature = self.signature
        if not signature:
            return None
        return sha256(f'{VERSION}:{signature}'.encode('ascii')).hexdigest()

    def describe(self):
        counts = Counter(element_id for element_id, _ in self.elements)
        return {
            'version': VERSION,
            'status': self.status,
            'signature': self.signature or None,
            'fingerprint_hash': self.fingerprint_hash,
            'elements': [{'id': element_id, 'name': IE_NAMES.get(element_id), 'length': length}
                         for element_id, length in self.elements],
            'duplicate_ids': sorted(element_id for element_id, count in counts.items() if count > 1),
            'excluded_ids': sorted(set(self.excluded_ids)),
            'possibly_truncated': self.possibly_truncated,
            'issues': list(self.issues),
        }


def parse_ie(ie: str | None) -> IEProfile:
    if ie is None or ie == '':
        return IEProfile('missing')
    if not isinstance(ie, str) or len(ie) > 200:
        return IEProfile('malformed', issues=('invalid_ie_type_or_size',))

    pairs = ie.split(',')
    if len(pairs) > MAX_WIRE_ELEMENTS:
        return IEProfile('malformed', issues=('too_many_elements',))

    elements = []
    excluded = []
    issues = []
    for position, pair in enumerate(pairs, 1):
        match = TOKEN.fullmatch(pair)
        if match is None:
            issues.append(f'invalid_pair_at_{position}')
            continue
        element_id, length = map(int, match.groups())
        if element_id > 255 or length > 255:
            issues.append(f'byte_out_of_range_at_{position}')
        elif element_id in PRIVATE_OR_AMBIGUOUS_IDS:
            excluded.append(element_id)
        else:
            elements.append((element_id, length))

    status = 'malformed' if issues else 'usable' if elements else 'no_usable_ie'
    return IEProfile(status, tuple(elements), tuple(excluded), len(pairs) == MAX_WIRE_ELEMENTS,
                     tuple(issues))


def fingerprint(ie):
    """Canonical text for callers that already expose the legacy string field."""
    return parse_ie(ie).signature


def ordered_match_count(left, right):
    previous = [0] * (len(right) + 1)
    for token in left:
        row = [0]
        for column, other in enumerate(right, 1):
            match = previous[column - 1] + 1 if token == other else max(row[-1], previous[column])
            row.append(match)
        previous = row
    return previous[-1]


def similarity(left: IEProfile, right: IEProfile) -> dict:
    """Compare observed IE structure and expose the evidence behind the score."""
    result = {'version': VERSION, 'score': None, 'left_status': left.status,
              'right_status': right.status,
              'possibly_truncated': left.possibly_truncated or right.possibly_truncated}
    if left.status != 'usable' or right.status != 'usable':
        return {**result, 'reason': 'insufficient_usable_ie'}

    left_counts, right_counts = Counter(left.elements), Counter(right.elements)
    shared = sum((left_counts & right_counts).values())
    union = sum((left_counts | right_counts).values())
    ordered = ordered_match_count(left.elements, right.elements)
    longest = max(len(left.elements), len(right.elements))
    composition_score = shared / union
    order_score = ordered / longest
    return {**result, 'score': (7 * composition_score + 3 * order_score) / 10,
            'composition_score': composition_score, 'order_score': order_score,
            'shared_token_count': shared, 'union_token_count': union,
            'ordered_match_count': ordered, 'max_token_count': longest}
