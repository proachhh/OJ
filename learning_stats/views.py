from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, FloatField, F
from django.db.models.functions import Cast
from problem.models import Problem, ProblemTag
from submission.models import Submission, JudgeStatus
from django.utils import timezone
from datetime import timedelta
from django.db.models.functions import TruncDate
from utils.neo4j_client import neo4j_client
import logging

logger = logging.getLogger(__name__)

@login_required
def learning_stats(request):
    user = request.user
    total_submissions = Submission.objects.filter(user_id=user.id).count()
    total_ac = Submission.objects.filter(user_id=user.id, result=JudgeStatus.ACCEPTED).count()
    accuracy = round(total_ac / total_submissions * 100, 1) if total_submissions else 0
    tags = ProblemTag.objects.all().prefetch_related('problem_set')
    tag_stats = []
    for tag in tags:
        problem_ids = tag.problem_set.values_list('id', flat=True)
        submissions = Submission.objects.filter(user_id=user.id, problem_id__in=problem_ids)
        total = submissions.count()
        ac = submissions.filter(result=JudgeStatus.ACCEPTED).count()
        acc_rate = round(ac / total * 100, 1) if total else 0
        tag_stats.append({
            'tag_name': tag.name,
            'total': total,
            'ac': ac,
            'accuracy': acc_rate,
        })
    tag_stats.sort(key=lambda x: x['accuracy'])
    beat_percent = get_beat_percent(user)
    lang_stats = []
    lang_groups = Submission.objects.filter(user_id=user.id).values('language').annotate(
        total=Count('id'),
        ac=Count('id', filter=Q(result=JudgeStatus.ACCEPTED))
    )
    for group in lang_groups:
        lang = group['language']
        total = group['total']
        ac = group['ac']
        acc_rate = round(ac / total * 100, 1) if total else 0
        lang_stats.append({
            'lang_name': lang,
            'total': total,
            'ac': ac,
            'accuracy': acc_rate,
        })
    lang_stats.sort(key=lambda x: x['accuracy'])
    data = {
        'total_submissions': total_submissions,
        'total_ac': total_ac,
        'accuracy': accuracy,
        'beat_percent': beat_percent,
        'tags': tag_stats,
        'lang_stats': lang_stats,
    }
    return JsonResponse(data)

def get_beat_percent(user):
    user_stats = Submission.objects.filter(user_id=user.id).aggregate(
        total_sub=Count('id'),
        total_ac=Count('id', filter=Q(result=JudgeStatus.ACCEPTED))
    )
    if user_stats['total_sub'] == 0:
        return 0.0
    user_accuracy = user_stats['total_ac'] / user_stats['total_sub'] * 100
    all_users_stats = Submission.objects.values('user_id').annotate(
        total_sub=Count('id'),
        total_ac=Count('id', filter=Q(result=JudgeStatus.ACCEPTED))
    ).filter(total_sub__gt=0).annotate(
        accuracy=Cast(F('total_ac'), FloatField()) / Cast(F('total_sub'), FloatField()) * 100
    ).order_by('-accuracy')
    higher_count = all_users_stats.filter(accuracy__gt=user_accuracy).count()
    total_users = all_users_stats.count()
    if total_users == 0:
        return 0.0
    beat = (total_users - higher_count) / total_users * 100
    return round(beat, 1)

@login_required
def learning_trend(request):
    days = int(request.GET.get('days', 7))
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days-1)
    submissions = Submission.objects.filter(
        user_id=request.user.id,
        create_time__date__gte=start_date,
        create_time__date__lte=end_date
    ).annotate(date=TruncDate('create_time')).values('date').annotate(
        total=Count('id'),
        ac=Count('id', filter=Q(result=JudgeStatus.ACCEPTED))
    ).order_by('date')
    date_range = [start_date + timedelta(days=i) for i in range(days)]
    result = []
    for d in date_range:
        item = next((s for s in submissions if s['date'] == d), None)
        if item and item['total'] > 0:
            rate = round(item['ac'] / item['total'] * 100, 1)
        else:
            rate = 0
        result.append({
            'date': d.strftime('%m/%d'),
            'accuracy': rate
        })
    return JsonResponse({'trend': result})

@login_required
def recommend(request):
    user = request.user
    username = user.username
    limit = int(request.GET.get('limit', 5))
    offset = int(request.GET.get('offset', 0))

    logger.warning(f"=== 推荐请求：用户 {username}, limit={limit}, offset={offset} ===")

    graph_recs = get_graph_recommendations(username, limit=50)
    logger.warning(f"图谱召回结果数量: {len(graph_recs)}")

    if len(graph_recs) < limit + offset:
        logger.warning("图谱召回不足，使用热度兜底")
        hot_recs = get_hot_recommendations(user, limit=50)
        logger.warning(f"热度兜底结果数量: {len(hot_recs)}")
        graph_recs.extend(hot_recs)
    else:
        logger.warning("图谱召回充足，不使用热度兜底")

    seen_ids = set()
    unique_recs = []
    for rec in graph_recs:
        pid = rec['id']
        if pid not in seen_ids:
            seen_ids.add(pid)
            unique_recs.append(rec)

    paged_recs = unique_recs[offset:offset+limit]
    total = len(unique_recs)

    problem_ids = [rec['id'] for rec in paged_recs]
    problems_map = {
        p.id: p for p in Problem.objects.filter(id__in=problem_ids).prefetch_related('tags')
    }

    data = []
    for rec in paged_recs:
        problem = problems_map.get(rec['id'])
        if not problem:
            continue
        data.append({
            '_id': problem._id,
            'title': problem.title,
            'difficulty': problem.difficulty,
            'tags': [tag.name for tag in problem.tags.all()],
            'reason': rec['reason'],
        })

    logger.warning(f"最终返回推荐数量: {len(data)}")
    return JsonResponse({'recommendations': data, 'total': total})

def get_graph_recommendations(username, limit=20):
    client = neo4j_client
    recs = []

    # 1. 内容召回
    content_query = """
    MATCH (u:User {username: $username})-[:SUBMITTED]->(s:Submission)-[:FOR]->(p:Problem)-[:BELONGS_TO]->(t:Topic)
    WHERE s.result = '0'
    WITH u, t, count(s) AS ac_count ORDER BY ac_count DESC LIMIT 3
    MATCH (t)<-[:BELONGS_TO]-(rec:Problem)
    WHERE NOT EXISTS { MATCH (u)-[:SUBMITTED]->(:Submission)-[:FOR]->(rec) }
    RETURN DISTINCT rec.problem_id AS id, rec._id AS display_id, rec.title AS title, 
           t.name AS reason_tag
    LIMIT $limit
    """
    try:
        result = client.run_query(content_query, {'username': username, 'limit': limit})
        for r in result:
            recs.append({
                'id': r['id'],
                'reason': f"基于您常做的「{r['reason_tag']}」题目推荐"
            })
    except Exception as e:
        logger.error(f"内容召回查询失败: {e}")

    # 2. 薄弱点召回
    if len(recs) < limit:
        weak_query = """
        MATCH (u:User {username: $username})-[:SUBMITTED]->(s:Submission)-[:FOR]->(p:Problem)-[:BELONGS_TO]->(t:Topic)
        WITH u, t, count(s) AS total, 
             sum(CASE WHEN s.result <> '0' THEN 1 ELSE 0 END) AS wrong
        WHERE total >= 3
        WITH t, wrong * 1.0 / total AS error_rate 
        ORDER BY error_rate DESC LIMIT 1
        MATCH (t)<-[:BELONGS_TO]-(rec:Problem)
        WHERE NOT EXISTS { 
            MATCH (u)-[:SUBMITTED]->(sub:Submission)-[:FOR]->(rec) 
            WHERE sub.result = '0' 
        }
        RETURN DISTINCT rec.problem_id AS id, rec._id AS display_id, rec.title AS title,
               t.name AS reason_tag
        LIMIT $limit
        """
        try:
            result = client.run_query(weak_query, {'username': username, 'limit': limit - len(recs)})
            for r in result:
                recs.append({
                    'id': r['id'],
                    'reason': f"巩固薄弱知识点「{r['reason_tag']}」"
                })
        except Exception as e:
            logger.error(f"薄弱点召回查询失败: {e}")

    # 3. 协同过滤召回
    if len(recs) < limit:
        cf_query = """
        MATCH (u:User {username: $username})-[:SUBMITTED]->(s1:Submission)-[:FOR]->(p:Problem)
        WHERE s1.result = '0'
        WITH u, collect(DISTINCT p) AS u_ac
        // 找到与 u 有共同 AC 题目的其他用户，并按共同题目数排序
        MATCH (other:User)-[:SUBMITTED]->(s2:Submission)-[:FOR]->(p)
        WHERE s2.result = '0' AND other <> u AND p IN u_ac
        WITH u, u_ac, other, count(DISTINCT p) AS common ORDER BY common DESC LIMIT 5
        // 推荐这些相似用户 AC 但 u 未做过的题目
        MATCH (other)-[:SUBMITTED]->(s3:Submission)-[:FOR]->(rec:Problem)
        WHERE s3.result = '0' AND NOT rec IN u_ac
        RETURN DISTINCT rec.problem_id AS id, rec._id AS display_id, rec.title AS title
        LIMIT $limit
        """
        try:
            result = client.run_query(cf_query, {'username': username, 'limit': limit - len(recs)})
            for r in result:
                recs.append({
                    'id': r['id'],
                    'reason': "与您学习路径相似的用户也做了此题"
                })
        except Exception as e:
            logger.error(f"协同过滤查询失败: {e}")

    return recs

def get_hot_recommendations(user, limit=20):
    done_ids = Submission.objects.filter(user_id=user.id).values_list('problem_id', flat=True).distinct()
    problems = Problem.objects.exclude(id__in=done_ids).order_by('-accepted_number')[:limit]
    recs = []
    for p in problems:
        user_tags = ProblemTag.objects.filter(
            problem__submission__user_id=user.id,
            problem__submission__result=JudgeStatus.ACCEPTED
        ).distinct()
        common_tags = p.tags.filter(id__in=user_tags).values_list('name', flat=True)
        if common_tags:
            reason = f"基于您做过的 {', '.join(common_tags[:2])} 题目推荐"
        else:
            reason = "热门题目推荐"
        recs.append({
            'id': p.id,
            'reason': reason
        })
    return recs