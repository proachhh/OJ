from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, FloatField, F
from django.db.models.functions import Cast
from problem.models import Problem, ProblemTag
from submission.models import Submission, JudgeStatus
from django.utils import timezone
from datetime import timedelta
from django.db.models.functions import TruncDate

# 返回当前用户的整体学习统计、知识点掌握情况以及在全体用户中的击败百分比。
@login_required
def learning_stats(request):
    user = request.user
    # 整体统计
    total_submissions = Submission.objects.filter(user_id=user.id).count()
    total_ac = Submission.objects.filter(user_id=user.id, result=JudgeStatus.ACCEPTED).count()
    accuracy = round(total_ac / total_submissions * 100, 1) if total_submissions else 0
    # 知识点统计
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
    # 击败百分比
    beat_percent = get_beat_percent(user)
    # 语言掌握统计
    lang_stats = []
    # 按语言分组统计提交次数和正确次数
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
    # 按正确率升序排序（与知识点保持一致）
    lang_stats.sort(key=lambda x: x['accuracy'])

    # 修改返回的 data 字典
    data = {
        'total_submissions': total_submissions,
        'total_ac': total_ac,
        'accuracy': accuracy,
        'beat_percent': beat_percent,
        'tags': tag_stats,
        'lang_stats': lang_stats,   # 新增字段
    }
    return JsonResponse(data)

# 辅助函数：计算当前用户的正确率在所有有提交记录的用户中的排名百分比（即击败了多少百分比的用户）。
def get_beat_percent(user):
    # 计算当前用户的正确率
    user_stats = Submission.objects.filter(user_id=user.id).aggregate(
        total_sub=Count('id'),
        total_ac=Count('id', filter=Q(result=JudgeStatus.ACCEPTED))
    )
    if user_stats['total_sub'] == 0:
        return 0.0
    user_accuracy = user_stats['total_ac'] / user_stats['total_sub'] * 100

    # 计算所有有提交记录的用户正确率
    all_users_stats = Submission.objects.values('user_id').annotate(
        total_sub=Count('id'),
        total_ac=Count('id', filter=Q(result=JudgeStatus.ACCEPTED))
    ).filter(total_sub__gt=0).annotate(
        accuracy=Cast(F('total_ac'), FloatField()) / Cast(F('total_sub'), FloatField()) * 100
    ).order_by('-accuracy')

    # 统计正确率高于当前用户的用户数
    higher_count = all_users_stats.filter(accuracy__gt=user_accuracy).count()
    total_users = all_users_stats.count()
    if total_users == 0:
        return 0.0
    beat = (total_users - higher_count) / total_users * 100
    return round(beat, 1)

# 为当前用户推荐未做过的题目，支持分页（limit 和 offset 参数），并返回每条推荐的理由。
@login_required
def recommend(request):
    user = request.user
    limit = int(request.GET.get('limit', 5))
    offset = int(request.GET.get('offset', 0))

    # 用户做过的题目 ID（去重）
    done_ids = Submission.objects.filter(user_id=user.id).values_list('problem_id', flat=True).distinct()
    # 推荐未做过的题目，按通过次数降序（热门程度）
    recommended = Problem.objects.exclude(id__in=done_ids).order_by('-accepted_number')[offset:offset+limit]
    total = Problem.objects.exclude(id__in=done_ids).count()

    data = []
    for p in recommended:
        reason = get_recommend_reason(user, p)
        data.append({
            '_id': p._id,
            'title': p.title,
            'difficulty': p.difficulty,
            'tags': [tag.name for tag in p.tags.all()],
            'reason': reason,
        })
    return JsonResponse({'recommendations': data, 'total': total})

# 辅助函数：基于用户已经正确解答的题目，分析当前推荐题目的标签交集，生成推荐理由。
def get_recommend_reason(user, problem):
    # 获取用户做过的题目的标签（仅考虑通过的题目）
    user_ac_problems = Submission.objects.filter(
        user_id=user.id,
        result=JudgeStatus.ACCEPTED
    ).values_list('problem_id', flat=True).distinct()
    user_tags = ProblemTag.objects.filter(problem__id__in=user_ac_problems).distinct()
    common_tags = problem.tags.filter(id__in=user_tags).values_list('name', flat=True)
    if common_tags:
        # 取最多两个标签作为理由
        tags_str = ', '.join(list(common_tags)[:2])
        return f"基于您做过的 {tags_str} 题目推荐"
    else:
        return "热门题目推荐"

# 返回当前用户最近 N 天的每日正确率。支持参数 days 来指定天数，默认值为 7。
@login_required
def learning_trend(request):
    days = int(request.GET.get('days', 7))
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days-1)

    # 获取用户每天的正确提交数和总提交数
    submissions = Submission.objects.filter(
        user_id=request.user.id,
        create_time__date__gte=start_date,
        create_time__date__lte=end_date
    ).annotate(date=TruncDate('create_time')).values('date').annotate(
        total=Count('id'),
        ac=Count('id', filter=Q(result=JudgeStatus.ACCEPTED))
    ).order_by('date')

    # 生成连续日期列表
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

