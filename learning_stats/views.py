from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from problem.models import Problem, Tag   # 根据实际路径调整
from submission.models import Submission

@login_required
def learning_stats(request):
    user = request.user

    # 整体统计
    total_submissions = Submission.objects.filter(user=user).count()
    total_ac = Submission.objects.filter(user=user, result=4).count()
    accuracy = round(total_ac / total_submissions * 100, 1) if total_submissions else 0

    # 知识点统计
    tags = Tag.objects.all().prefetch_related('problem_set')
    tag_stats = []
    for tag in tags:
        # 该标签下的所有题目
        problem_ids = tag.problem_set.values_list('id', flat=True)
        # 用户在这些题目上的提交
        submissions = Submission.objects.filter(user=user, problem_id__in=problem_ids)
        total = submissions.count()
        ac = submissions.filter(result=4).count()
        acc_rate = round(ac / total * 100, 1) if total else 0
        tag_stats.append({
            'tag_name': tag.name,
            'total': total,
            'ac': ac,
            'accuracy': acc_rate,
        })
    # 按正确率升序排序（薄弱点在前）
    tag_stats.sort(key=lambda x: x['accuracy'])

    data = {
        'total_submissions': total_submissions,
        'total_ac': total_ac,
        'accuracy': accuracy,
        'tags': tag_stats,
    }
    return JsonResponse(data)

@login_required
def recommend(request):
    user = request.user
    # 用户已经做过的题目 ID（去重）
    done_ids = Submission.objects.filter(user=user).values_list('problem_id', flat=True).distinct()
    # 推荐未做过的题目，按通过次数降序（热门程度）
    recommended = Problem.objects.exclude(id__in=done_ids).order_by('-accepted_number')[:10]
    data = [{
        'id': p.id,
        'title': p.title,
        'difficulty': p.difficulty,  # 如果 Problem 有 difficulty 字段
        'tags': [tag.name for tag in p.tags.all()],
    } for p in recommended]
    return JsonResponse({'recommendations': data})