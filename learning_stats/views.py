from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from problem.models import Problem, ProblemTag
from submission.models import Submission

@login_required
def learning_stats(request):
    user = request.user

    # 整体统计
    total_submissions = Submission.objects.filter(user=user).count()
    total_ac = Submission.objects.filter(user=user, result=4).count()
    accuracy = round(total_ac / total_submissions * 100, 1) if total_submissions else 0

    # 知识点统计
    tags = ProblemTag.objects.all().prefetch_related('problem_set')
    tag_stats = []
    for tag in tags:
        problem_ids = tag.problem_set.values_list('id', flat=True)
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
        'tags': [tag.name for tag in p.tags.all()],   # 注意：Problem 的 tags 字段是 ManyToManyField，这里取所有关联的 ProblemTag 的 name
    } for p in recommended]
    return JsonResponse({'recommendations': data})