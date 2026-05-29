import unittest

from trendradar.ai.analyzer import AIAnalyzer


class AIAnalyzerClusterPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = AIAnalyzer.__new__(AIAnalyzer)

    def test_security_related_china_cluster_is_promoted_to_first(self) -> None:
        clusters = [
            {
                "title": "地方民生争议：补贴规则引发讨论",
                "summary": "多地围绕补贴政策和执行口径出现争议。",
                "risk": "舆情继续发酵。",
                "action": "继续观察。",
                "items": [],
            },
            {
                "title": "涉华安全议题：外媒集中炒作间谍指控",
                "summary": "多家国际媒体围绕中国、国家安全和间谍定罪持续跟进。",
                "risk": "可能放大外交安全压力和国际形象争议。",
                "action": "持续观察跨源扩散。",
                "items": [],
            },
            {
                "title": "市场金融波动：板块分化延续",
                "summary": "市场关注风险偏好变化。",
                "risk": "情绪继续震荡。",
                "action": "关注后续数据。",
                "items": [],
            },
        ]

        reordered = self.analyzer._prioritize_security_related_china_cluster(clusters)

        self.assertEqual(reordered[0]["title"], "涉华安全议题：外媒集中炒作间谍指控")
        self.assertEqual(reordered[1]["title"], "地方民生争议：补贴规则引发讨论")
        self.assertEqual(reordered[2]["title"], "市场金融波动：板块分化延续")

    def test_non_security_clusters_keep_original_order(self) -> None:
        clusters = [
            {
                "title": "宏观经济：物价数据承压",
                "summary": "市场关注需求恢复节奏。",
                "risk": "预期仍然偏弱。",
                "action": "继续跟踪。",
                "items": [],
            },
            {
                "title": "平台治理：短视频整治升级",
                "summary": "内容治理讨论升温。",
                "risk": "争议继续扩散。",
                "action": "关注规则变化。",
                "items": [],
            },
        ]

        reordered = self.analyzer._prioritize_security_related_china_cluster(clusters)

        self.assertEqual(reordered, clusters)

    def test_domestic_public_safety_cluster_is_not_misclassified(self) -> None:
        clusters = [
            {
                "title": "地方民生争议：补贴规则引发讨论",
                "summary": "多地围绕补贴政策和执行口径出现争议。",
                "risk": "舆情继续发酵。",
                "action": "继续观察。",
                "items": [],
            },
            {
                "title": "浏阳爆炸追责",
                "summary": "中国国务院调查组介入，安全生产治理争议升温。",
                "risk": "可能放大对地方治理的批评。",
                "action": "继续观察事故处置。",
                "items": [
                    {
                        "title": "The death toll from an explosion at a fireworks plant in China rises to 37",
                        "source_name": "美联社-中国",
                    }
                ],
            },
            {
                "title": "涉华外交安全",
                "summary": "外媒围绕涉华间谍指控、中英关系和外交安全持续放大。",
                "risk": "可能继续推高国际形象争议。",
                "action": "持续观察跨源扩散。",
                "items": [],
            },
        ]

        reordered = self.analyzer._prioritize_security_related_china_cluster(clusters)

        self.assertEqual(reordered[0]["title"], "涉华外交安全")


if __name__ == "__main__":
    unittest.main()
