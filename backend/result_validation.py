"""Keep independently valid model records; never infer missing evidence or labels."""
import json
from collections import Counter
from pydantic import ValidationError
from .schemas import AutoAnalysis, Evidence, Tag, Claim, ProposedLabel
from .database import labels


def prepare(c, paper, raw):
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('AI 返回必须是 JSON 对象')
    issues = []
    def note(message):
        issues.append(message)
    def records(field):
        value = data.get(field, [])
        if not isinstance(value, list):
            note(f'{field} 不是数组，未保存该部分')
            return []
        if field not in data and field in ('tags', 'claims'):
            note(f'缺少 {field}，该部分未提供')
        return value
    def evidence(value, location):
        valid = []
        if not isinstance(value, list):
            note(f'{location} 的证据不是数组')
            return valid
        for index, item in enumerate(value, 1):
            try:
                checked = Evidence.model_validate(item)
                if not checked.page or checked.page > paper['page_count'] or not checked.quote.strip():
                    raise ValueError('missing page or quote')
                entry = checked.model_dump()
                entry['block_id'] = ''
                valid.append(entry)
            except (ValidationError, ValueError):
                note(f'{location} 证据 {index} 缺少有效页码/原文或格式错误，未使用')
        return valid
    proposals = []
    proposed_keys = set()
    for index, item in enumerate(records('new_labels'), 1):
        try:
            proposal = ProposedLabel.model_validate(item).model_dump()
            if proposal['key'] in proposed_keys:
                raise ValueError('duplicate key')
            proposals.append(proposal)
            proposed_keys.add(proposal['key'])
        except (ValidationError, ValueError):
            note(f'新标签 {index} 缺少完整定义或格式错误，未创建')
    allowed = {row['id'] for row in labels(c) if row['active'] and row['dimension'] != 'personal'} | proposed_keys
    valid_tags = []
    for index, item in enumerate(records('tags'), 1):
        if not isinstance(item, dict) or not isinstance(item.get('label_id'), str) or item.get('label_id') not in allowed:
            note(f'标签 {index} 未定义、停用或属于私人用途，未加入筛选：{item.get("label_id", "缺失") if isinstance(item, dict) else "格式错误"}')
            continue
        entry = dict(item)
        entry['evidence'] = evidence(entry.get('evidence'), f'标签 {index}')
        try:
            valid_tags.append(Tag.model_validate(entry).model_dump())
        except ValidationError:
            note(f'标签 {index} 没有有效证据或字段错误，未保存')
    candidates = records('claims')
    duplicate_ids = Counter(item.get('id') for item in candidates if isinstance(item, dict) and isinstance(item.get('id'), str))
    valid_claims = []
    for index, item in enumerate(candidates, 1):
        if not isinstance(item, dict):
            note(f'断言 {index} 不是对象，未保存')
            continue
        entry = dict(item)
        if isinstance(entry.get('id'), str) and duplicate_ids.get(entry['id'], 0) > 1:
            note(f'断言 {index} 的 id 重复，未选择其中任何一条')
            continue
        if isinstance(entry.get('conditions'), str):
            entry['conditions'] = [entry['conditions']] if entry['conditions'] else []
        refs = entry.get('label_ids')
        if isinstance(refs, list) and all(isinstance(ref, str) for ref in refs):
            unknown = [ref for ref in refs if ref not in allowed]
            if unknown:
                note(f'断言 {index} 的未定义或停用标签未加入筛选：' + '、'.join(unknown))
            entry['label_ids'] = list(dict.fromkeys(ref for ref in refs if ref in allowed))
        entry['evidence'] = evidence(entry.get('evidence'), f'断言 {index}')
        try:
            valid_claims.append(Claim.model_validate(entry).model_dump())
        except ValidationError as exc:
            fields = ', '.join(str(error['loc'][0]) for error in exc.errors())
            note(f'断言 {index} 缺少有效证据或必要字段（{fields}），未保存')
    if issues and not valid_tags and not valid_claims:
        raise ValueError('没有通过校验的标签或断言；' + '；'.join(dict.fromkeys(issues))[:1400])
    used = {tag['label_id'] for tag in valid_tags} | {ref for claim in valid_claims for ref in claim['label_ids']}
    data['tags'] = valid_tags
    data['claims'] = valid_claims
    data['new_labels'] = [proposal for proposal in proposals if proposal['key'] in used]
    return AutoAnalysis.model_validate(data).model_dump(), list(dict.fromkeys(issues))
