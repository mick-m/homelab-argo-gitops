# Applies rules.yaml to Paperless's database. Run with
#   python3 manage.py shell < apply_rules.py
# (by the paperless-rules Job). Idempotent: by name, create or update; never
# deletes anything that is not in the file. Written against Paperless 3.4.1
# models (documents.models: MatchingModel, Workflow, WorkflowTrigger,
# WorkflowAction).
import os
import yaml
from django.db import transaction
from documents.models import (Correspondent, DocumentType, MatchingModel, Tag,
                              Workflow, WorkflowAction, WorkflowTrigger)

RULES = os.environ.get("PAPERLESS_RULES_FILE", "/usr/src/paperless/scripts/rules.yaml")
ALGO = {"none": MatchingModel.MATCH_NONE, "any": MatchingModel.MATCH_ANY,
        "all": MatchingModel.MATCH_ALL, "exact": MatchingModel.MATCH_LITERAL,
        "regex": MatchingModel.MATCH_REGEX, "fuzzy": MatchingModel.MATCH_FUZZY,
        "auto": MatchingModel.MATCH_AUTO}
log = []


def ensure(model, spec):
    """Create or update one MatchingModel by name; returns the object."""
    obj, created = model.objects.get_or_create(name=spec["name"])
    want = {"matching_algorithm": ALGO[spec.get("matching", "none")],
            "match": spec.get("match", ""), "is_insensitive": True}
    changed = [k for k, v in want.items() if getattr(obj, k) != v]
    for k in changed:
        setattr(obj, k, want[k])
    if created or changed:
        obj.save()
        log.append(f"{'created' if created else 'updated'} {model.__name__} {obj.name}"
                   + (f" ({', '.join(changed)})" if changed and not created else ""))
    return obj


def by_name(model, name):
    if name is None:
        return None
    return model.objects.get(name=name)


with open(RULES) as f:
    rules = yaml.safe_load(f)

with transaction.atomic():
    for spec in rules.get("document_types", []):
        ensure(DocumentType, spec)
    for spec in rules.get("tags", []):
        ensure(Tag, spec)
    for spec in rules.get("correspondents", []):
        ensure(Correspondent, spec)

    for wf in rules.get("workflows", []):
        when, act = wf.get("when", {}), wf.get("set", {})
        w, created = Workflow.objects.get_or_create(name=wf["name"], defaults={"order": wf.get("order", 0)})
        w.order, w.enabled = wf.get("order", 0), wf.get("enabled", True)
        w.save()
        # Triggers and actions belong to the workflow: replace them with the file's.
        for t in w.triggers.all():
            t.delete()
        for a in w.actions.all():
            a.delete()
        trig = WorkflowTrigger.objects.create(
            type=WorkflowTrigger.WorkflowTriggerType.DOCUMENT_ADDED,
            filter_filename=when.get("filename"),
            filter_has_correspondent=by_name(Correspondent, when.get("correspondent")),
            filter_has_document_type=by_name(DocumentType, when.get("document_type")),
            matching_algorithm=WorkflowTrigger.WorkflowTriggerMatching.NONE,
        )
        action = WorkflowAction.objects.create(
            type=WorkflowAction.WorkflowActionType.ASSIGNMENT,
            assign_title=act.get("title"),
            assign_document_type=by_name(DocumentType, act.get("document_type")),
        )
        action.assign_tags.set([by_name(Tag, n) for n in act.get("tags", [])])
        w.triggers.set([trig])
        w.actions.set([action])
        log.append(f"{'created' if created else 'applied'} workflow {w.name}")

print("paperless-rules: " + ("; ".join(log) if log else "nothing to change"))
