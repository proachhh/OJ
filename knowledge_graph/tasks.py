# knowledge_graph/tasks.py
import dramatiq
import logging
from utils.neo4j_client import neo4j_client

logger = logging.getLogger(__name__)


@dramatiq.actor(max_retries=3)
def update_topic_difficulty():
    """根据用户实际提交数据，自动校准知识点难度"""
    client = neo4j_client

    query = """
    MATCH (t:Topic)<-[:BELONGS_TO]-(:Problem)<-[:FOR]-(s:Submission)-[:SUBMITTED]->(u:User)
    WITH t, count(s) AS total_submissions,
         sum(CASE WHEN s.result = 0 THEN 1 ELSE 0 END) AS ac_count
    WHERE total_submissions >= 5
    WITH t, total_submissions, ac_count,
         (ac_count * 1.0 / total_submissions) AS pass_rate
    SET t.pass_rate = round(pass_rate, 3),
        t.total_submissions = total_submissions,
        t.ac_count = ac_count,
        t.calculated_difficulty = CASE
            WHEN pass_rate < 0.3 THEN 'Hard'
            WHEN pass_rate < 0.6 THEN 'Medium'
            ELSE 'Easy'
        END
    RETURN t.name AS topic, pass_rate, calculated_difficulty
    """

    try:
        with client._driver.session() as session:
            result = session.run(query)
            records = [record.data() for record in result]
        logger.info(f"Updated difficulty for {len(records)} topics")
    except Exception as e:
        logger.exception(f"Failed to update topic difficulty: {e}")
        raise


@dramatiq.actor(max_retries=3)
def update_problem_difficulty():
    """根据实际通过率校准题目难度"""
    client = neo4j_client

    query = """
    MATCH (p:Problem)<-[:FOR]-(s:Submission)
    WITH p, count(s) AS total_submissions,
         sum(CASE WHEN s.result = 0 THEN 1 ELSE 0 END) AS ac_count
    WHERE total_submissions >= 3
    WITH p, total_submissions, ac_count,
         (ac_count * 1.0 / total_submissions) AS pass_rate
    SET p.pass_rate = round(pass_rate, 3),
        p.total_submissions = total_submissions,
        p.ac_count = ac_count,
        p.calculated_difficulty = CASE
            WHEN pass_rate < 0.2 THEN 'Hard'
            WHEN pass_rate < 0.5 THEN 'Medium'
            ELSE 'Easy'
        END
    RETURN p.problem_id AS id, pass_rate, calculated_difficulty
    """

    try:
        with client._driver.session() as session:
            result = session.run(query)
            records = [record.data() for record in result]
        logger.info(f"Updated difficulty for {len(records)} problems")
    except Exception as e:
        logger.exception(f"Failed to update problem difficulty: {e}")
        raise


@dramatiq.actor(max_retries=3)
def discover_topic_correlations(min_cooccurrence=10, min_confidence=0.3):
    """通过共现分析发现知识点之间的关联关系 (优化版)"""
    client = neo4j_client

    # 分步查询: 先计算每个知识点涉及的用户集合大小(作为分母)
    # 再计算两两共现次数
    # 使用 UNWIND + 子查询避免路径模式错误
    query = """
    MATCH (t:Topic)<-[:BELONGS_TO]-(:Problem)<-[:FOR]-(s:Submission)-[:SUBMITTED]->(u:User)
    WHERE s.result = 0
    WITH t, collect(DISTINCT u.user_id) AS users
    SET t.user_list = users, t.user_count = size(users)  // 临时属性，可后续删除

    MATCH (t1:Topic), (t2:Topic)
    WHERE t1 <> t2 AND t1.user_count >= $min_cooccurrence AND t2.user_count >= $min_cooccurrence
    WITH t1, t2, [u IN t1.user_list WHERE u IN t2.user_list] AS common_users
    WHERE size(common_users) >= $min_cooccurrence
    WITH t1, t2, size(common_users) AS cooccurrence,
         size(common_users) * 1.0 / t1.user_count AS confidence
    WHERE confidence >= $min_confidence
    MERGE (t1)-[r:RELATED_TO]->(t2)
    SET r.weight = round(confidence, 3),
        r.cooccurrence = cooccurrence,
        r.updated_at = datetime()
    RETURN t1.name AS source, t2.name AS target, confidence, cooccurrence
    ORDER BY confidence DESC
    """

    try:
        with client._driver.session() as session:
            result = session.run(query, {
                'min_cooccurrence': min_cooccurrence,
                'min_confidence': min_confidence
            })
            records = [record.data() for record in result]
        logger.info(f"Discovered {len(records)} topic correlations")
        # 可选：清理临时属性
        cleanup = "MATCH (t:Topic) REMOVE t.user_list, t.user_count"
        client.run_query(cleanup)
    except Exception as e:
        logger.exception(f"Failed to discover topic correlations: {e}")
        raise


@dramatiq.actor(max_retries=3)
def update_user_mastery(user_id):
    """更新用户对各个知识点的掌握程度"""
    from submission.models import Submission

    try:
        submissions = Submission.objects.select_related('problem').filter(
            user_id=user_id
        )
    except Exception as e:
        logger.error(f"Failed to get submissions for user {user_id}: {e}")
        return

    client = neo4j_client

    topic_stats = {}
    for sub in submissions:
        for tag in sub.problem.tags.all():
            if tag.name not in topic_stats:
                topic_stats[tag.name] = {'total': 0, 'ac': 0}
            topic_stats[tag.name]['total'] += 1
            if sub.result == 0:
                topic_stats[tag.name]['ac'] += 1

    try:
        with client._driver.session() as session:
            for topic_name, stats in topic_stats.items():
                mastery_rate = stats['ac'] / stats['total'] if stats['total'] > 0 else 0

                session.run(
                    """
                    MATCH (u:User {user_id: $user_id})
                    MATCH (t:Topic {name: $topic})
                    MERGE (u)-[r:MASTERS]->(t)
                    SET r.attempts = $total,
                        r.successes = $ac,
                        r.mastery_rate = round($mastery_rate, 3),
                        r.updated_at = datetime()
                    """,
                    {
                        'user_id': user_id,
                        'topic': topic_name,
                        'total': stats['total'],
                        'ac': stats['ac'],
                        'mastery_rate': mastery_rate
                    }
                )
        logger.info(f"Updated mastery for user {user_id} on {len(topic_stats)} topics")
    except Exception as e:
        logger.exception(f"Failed to update user mastery for user {user_id}: {e}")
        raise


@dramatiq.actor(max_retries=3)
def run_full_graph_learning():
    """运行完整的知识图谱自学习流程"""
    logger.info("Starting full graph learning process...")

    try:
        update_topic_difficulty.send()
        logger.info("Topic difficulty updated")

        update_problem_difficulty.send()
        logger.info("Problem difficulty updated")

        discover_topic_correlations.send()
        logger.info("Topic correlations discovered")

        logger.info("Full graph learning process completed")
    except Exception as e:
        logger.exception(f"Full graph learning process failed: {e}")
        raise
