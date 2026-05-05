from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from account.models import User, UserProfile
from problem.models import Problem
from submission.models import Submission, JudgeStatus


class Command(BaseCommand):
    help = '修复 Problem 和 UserProfile 的 submission_number / accepted_number 计数器'

    def handle(self, *args, **options):
        self.stdout.write('修复题目计数器...')
        problem_count = 0
        for problem in Problem.objects.filter(contest__isnull=True):
            subs = Submission.objects.filter(problem=problem, contest__isnull=True)
            problem.submission_number = subs.count()
            problem.accepted_number = subs.filter(result=JudgeStatus.ACCEPTED).count()
            problem.save(update_fields=['submission_number', 'accepted_number'])
            problem_count += 1
        self.stdout.write(f'  已修复 {problem_count} 道题目')

        self.stdout.write('修复用户计数器...')
        user_count = 0
        for user in User.objects.all():
            profile, _ = UserProfile.objects.get_or_create(user=user)
            subs = Submission.objects.filter(user_id=user.id, contest__isnull=True)
            profile.submission_number = subs.count()
            profile.accepted_number = subs.filter(result=JudgeStatus.ACCEPTED).count()
            profile.save(update_fields=['submission_number', 'accepted_number'])
            user_count += 1
        self.stdout.write(f'  已修复 {user_count} 个用户')

        self.stdout.write(self.style.SUCCESS('计数器修复完成！'))
