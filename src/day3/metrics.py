"""Fixed judged projections and participant-level descriptive summaries."""
from collections import Counter, defaultdict
from itertools import combinations
import math
from statistics import mean

from ..common import require
from ..day2.core import graded_utility, ranking_relations

METRICS = ('ndcg@3', 'ndcg@5', 'pairwise_agreement', 'kendall_tau_b')


def sign(value, tolerance=1e-12):
    return None if value is None else (1 if value > tolerance else -1 if value < -tolerance else 0)


def tau_b(x, y):
    require(len(x) == len(y), 'Kendall lengths differ')
    concordant = discordant = xonly = yonly = 0
    for i, j in combinations(range(len(x)), 2):
        dx = (x[i] > x[j]) - (x[i] < x[j])
        dy = (y[i] > y[j]) - (y[i] < y[j])
        if dx and dy:
            concordant += dx == dy
            discordant += dx != dy
        elif not dx and dy:
            xonly += 1
        elif dx and not dy:
            yonly += 1
    denominator = math.sqrt((concordant+discordant+xonly)*(concordant+discordant+yonly))
    return (concordant-discordant)/denominator if denominator else None


def evaluate(ranking, grades):
    require(set(grades) <= {r[0] for r in ranking}, 'foreign qrel')
    require(all(g is None or type(g) is int and 0 <= g <= 3 for g in grades.values()), 'invalid qrel')
    known = {k:g for k,g in grades.items() if g is not None}
    scores = {k:s for k,s,_ in ranking if k in known}
    credit = []
    for a,b in combinations(sorted(known),2):
        if known[a] == known[b]:
            continue
        predicted = (scores[a]>scores[b])-(scores[a]<scores[b])
        actual = (known[a]>known[b])-(known[a]<known[b])
        credit.append(0.5 if predicted == 0 else int(predicted == actual))
    keys = sorted(known)
    return {'ndcg@3':graded_utility(ranking, grades, 3),
            'ndcg@5':graded_utility(ranking, grades, 5),
            'pairwise_agreement':mean(credit) if credit else None,
            'kendall_tau_b':tau_b([scores[k] for k in keys],[known[k] for k in keys]),
            'known_candidates':len(known),'strict_reference_pairs':len(credit)}


def delta(after, before):
    return None if after is None or before is None else after-before


def value_record(arms):
    return {m:{'delta_C':delta(arms['C'][m],arms['B'][m]),
               'delta_D':delta(arms['D'][m],arms['B'][m]),
               'delta_delta':delta(arms['C'][m],arms['D'][m])}
            for m in METRICS}


def changes(before, after, grades):
    old,new = ranking_relations(before),ranking_relations(after)
    require(set(old)==set(new),'different ranking candidates')
    scores = {k:s for k,s,_ in before}
    changed_scores=sum(abs(s-scores[k])>1e-12 for k,s,_ in after)
    details=[]
    for a,b in sorted(old):
        if old[a,b] == new[a,b]:
            continue
        ga,gb=grades.get(a),grades.get(b)
        preference=None if ga is None or gb is None else (ga>gb)-(ga<gb)
        def credit(relation):
            return None if preference in (None,0) else 0.5 if relation==0 else int(relation==preference)
        details.append({'candidate_pair':[a,b], 'before':old[a,b], 'after':new[a,b],
                        'reference_preference':preference,
                        'pair_credit_delta':delta(credit(new[a,b]),credit(old[a,b]))})
    return {'candidate_score_changes':changed_scores,'total_pairs':len(old),
            'changed_relations':len(details),
            'tie_relation_changes':sum(d['before']==0 or d['after']==0 for d in details),
            'strict_order_reversals':sum(d['before']*d['after']==-1 for d in details),
            'ranking_changed':bool(details),'pair_details':details}


def summarize(records, getter):
    """Never use candidate pairs as independent samples; no p-values."""
    grouped=defaultdict(list)
    signs=Counter()
    for row in records:
        value=getter(row)
        signs[{None:'undetermined',-1:'negative',0:'zero',1:'positive'}[sign(value)]]+=1
        if value is not None:grouped[row['participant']].append(value)
    effects={p:mean(v) for p,v in sorted(grouped.items())}
    vals=list(effects.values())
    return {'participant_macro_mean':mean(vals) if vals else None,
            'participant_effects':effects,
            'participant_context_counts':{p:len(v) for p,v in sorted(grouped.items())},
            'participant_min':min(vals) if vals else None,'participant_max':max(vals) if vals else None,
            'leave_one_participant_out':{p:mean([v for q,v in effects.items() if p!=q]) if len(effects)>1 else None for p in effects},
            'context_sign_counts':dict(signs),'evaluated_contexts':sum(len(v) for v in grouped.values()),
            'population_significance_claim':False}


def cost_scenarios(records, costs, penalties):
    output=[]
    for cc,cd in costs:
        for penalty in penalties:
            output.append({'C_cost':cc,'D_cost':cd,'penalty':penalty,
                           'net_C_minus_D':summarize(records,lambda r:None if r['value']['ndcg@5']['delta_delta'] is None else r['value']['ndcg@5']['delta_delta']-penalty*(cc-cd))})
    return output
