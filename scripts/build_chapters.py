"""build_chapters.py —— 从数据源生成章节索引 (chapters.json)

从两个数据源构建统一章节结构:
  1. CS-Base (八股) — 目录结构 + README.md 中文章名
  2. LeetCode (算法) — 72个 topic tag 合并为 ~17 个算法章

Usage:
    conda run -n helloagents python scripts/build_chapters.py
"""

import json
import os
import re
from pathlib import Path
from collections import Counter, defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CS_BASE_DIR = PROJECT_ROOT / "data" / "cs_fundamentals" / "CS-Base"
LEETCODE_FILE = PROJECT_ROOT / "data" / "leetcode" / "leetcode-problems" / "merged_problems.json"
OUTPUT_FILE = PROJECT_ROOT / "data" / "chapters.json"

# 不纳入技术学习的目录
SKIP_DIRS = {"cs_learn", "reader_nb", "README.md"}
# 只处理这四个技术主题
TECH_SUBJECTS = {"mysql", "network", "os", "redis"}

# ====================================================================
# Part 1: CS-Base 章节抽取
# ====================================================================

# 从 README.md 提取的中文章节名映射: {subject: {subdir: (chapter_name_zh, chapter_order)}}
README_CHAPTER_MAP = {
    "mysql": {
        "base":          ("基础篇", 1),
        "index":         ("索引篇", 2),
        "transaction":   ("事务篇", 3),
        "lock":          ("锁篇", 4),
        "log":           ("日志篇", 5),
        "buffer_pool":   ("内存篇", 6),
    },
    "network": {
        "1_base":    ("网络基础篇", 1),
        "2_http":    ("HTTP 篇", 2),
        "3_tcp":     ("TCP 篇", 3),
        "4_ip":      ("IP 篇", 4),
        "5_learn":   ("学习心得", 5),
    },
    "os": {
        "1_hardware":        ("硬件结构", 1),
        "2_os_structure":    ("操作系统结构", 2),
        "3_memory":          ("内存管理", 3),
        "4_process":         ("进程管理", 4),
        "5_schedule":        ("调度算法", 5),
        "6_file_system":     ("文件系统", 6),
        "7_device":          ("设备管理", 7),
        "8_network_system":  ("网络系统", 8),
        "9_linux_cmd":       ("Linux 命令", 9),
        "10_learn":          ("学习心得", 10),
    },
    "redis": {
        "base":          ("面试篇", 1),
        "data_struct":   ("数据类型篇", 2),
        "storage":       ("持久化篇", 3),
        "module":        ("功能篇", 4),
        "cluster":       ("高可用篇", 5),
        "architecture":  ("缓存篇", 6),
    },
}

# TCP 子章节拆分 (network/3_tcp/ 共 23 篇文章，490K 字，是唯一需要拆分的章节)
# 基于文章标题和编号的自然分组:
TCP_SUB_CHAPTERS = [
    {
        "id": "tcp-connection",
        "name_zh": "连接管理",
        "name_en": "TCP Connection Management",
        "description": "三次握手、四次挥手、序列号、SYN/FIN 处理、TIME_WAIT 等",
        "files": [
            "tcp_interview.md",
            "tcp_stream.md",
            "isn_deff.md",
            "syn_drop.md",
            "challenge_ack.md",
            "out_of_order_fin.md",
            "time_wait_recv_syn.md",
            "tcp_three_fin.md",
        ],
    },
    {
        "id": "tcp-reliability",
        "name_zh": "可靠传输与优化",
        "name_en": "TCP Reliability & Performance",
        "description": "重传机制、滑动窗口、流量控制、拥塞控制、抓包分析、队列管理",
        "files": [
            "tcp_feature.md",
            "tcp_tcpdump.md",
            "tcp_queue.md",
            "tcp_optimize.md",
            "tcp_problem.md",
            "tcp_drop.md",
        ],
    },
    {
        "id": "tcp-edge-cases",
        "name_zh": "实战与边界场景",
        "name_en": "TCP Edge Cases & Real-world Scenarios",
        "description": "断电/断网行为、TLS 协作、KeepAlive、端口复用、listen/accept、UDP 可靠传输",
        "files": [
            "tcp_down_and_crash.md",
            "tcp_unplug_the_network_cable.md",
            "tcp_tls.md",
            "tcp_tw_reuse_close.md",
            "tcp_http_keepalive.md",
            "tcp_no_listen.md",
            "tcp_no_accpet.md",
            "quic.md",
            "port.md",
        ],
    },
]


def _read_h1_title(md_path: Path) -> str:
    """提取 markdown 文件的第一行 H1 标题"""
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("# ") and not stripped.startswith("## "):
                    return stripped[2:].strip()
    except Exception:
        pass
    return md_path.stem


def _count_chars(md_path: Path) -> int:
    """统计文件字符数"""
    try:
        return len(md_path.read_text(encoding="utf-8"))
    except Exception:
        return 0


def build_cs_chapters() -> list[dict]:
    """从 CS-Base 目录结构构建章节列表"""
    chapters = []

    for subject_dir in sorted(CS_BASE_DIR.iterdir()):
        if not subject_dir.is_dir():
            continue
        subject = subject_dir.name
        if subject in SKIP_DIRS or subject not in TECH_SUBJECTS:
            continue

        chapter_map = README_CHAPTER_MAP.get(subject, {})
        subdirs = [d for d in subject_dir.iterdir() if d.is_dir()]

        for subdir in sorted(subdirs):
            sub_name = subdir.name
            if sub_name in SKIP_DIRS:
                continue

            info = chapter_map.get(sub_name, (sub_name, 99))
            name_zh, order = info

            files = sorted(subdir.glob("*.md"))
            # 过滤 README.md
            files = [f for f in files if f.name.lower() != "readme.md"]
            file_list = [f.name for f in files]
            total_chars = sum(_count_chars(f) for f in files)
            article_titles = [_read_h1_title(f) for f in files]

            # TCP 特殊处理: 拆分为子章节
            if subject == "network" and sub_name == "3_tcp":
                for sc in TCP_SUB_CHAPTERS:
                    sc_files = [f for f in file_list if f in sc["files"]]
                    sc_chars = sum(_count_chars(subdir / f) for f in sc_files)
                    sc_titles = [_read_h1_title(subdir / f) for f in sc_files]
                    chapters.append({
                        "id": f"{subject}-{sc['id']}",
                        "subject": subject,
                        "subject_zh": _subject_name_zh(subject),
                        "mode": "cs_fundamentals",
                        "name_zh": sc["name_zh"],
                        "name_en": sc["name_en"],
                        "description": sc["description"],
                        "parent_chapter": name_zh,
                        "source_dir": f"{subject}/{sub_name}",
                        "file_count": len(sc_files),
                        "approx_chars": sc_chars,
                        "article_titles": sc_titles,
                    })
            else:
                chapters.append({
                    "id": f"{subject}-{sub_name}",
                    "subject": subject,
                    "subject_zh": _subject_name_zh(subject),
                    "mode": "cs_fundamentals",
                    "name_zh": name_zh,
                    "name_en": sub_name.replace("_", " ").title(),
                    "description": "",
                    "source_dir": f"{subject}/{sub_name}",
                    "file_count": len(file_list),
                    "approx_chars": total_chars,
                    "article_titles": article_titles,
                })

    return chapters


def _subject_name_zh(subject: str) -> str:
    """主题英文名 → 中文名"""
    return {
        "mysql": "MySQL",
        "network": "计算机网络",
        "os": "操作系统",
        "redis": "Redis",
    }.get(subject, subject)


# ====================================================================
# Part 2: LeetCode 章节分组
# ====================================================================

# 72 个 LeetCode tag → ~17 个算法章
LEETCODE_TAXONOMY = {
    "数组与字符串": {
        "id": "array-string",
        "name_en": "Arrays & Strings",
        "description": "数组操作、双指针、滑动窗口、前缀和、矩阵",
        "topics": [
            "Array", "String", "Matrix", "Prefix Sum",
            "Two Pointers", "Sliding Window",
        ],
    },
    "哈希与计数": {
        "id": "hash-counting",
        "name_en": "Hashing & Counting",
        "description": "哈希表、哈希函数、计数排序",
        "topics": [
            "Hash Table", "Hash Function", "Counting",
            "Counting Sort",
        ],
    },
    "链表": {
        "id": "linked-list",
        "name_en": "Linked Lists",
        "description": "单链表、双链表操作",
        "topics": [
            "Linked List", "Doubly-Linked List",
        ],
    },
    "栈与队列": {
        "id": "stack-queue",
        "name_en": "Stacks & Queues",
        "description": "栈、队列、单调栈、单调队列",
        "topics": [
            "Stack", "Queue", "Monotonic Stack", "Monotonic Queue",
        ],
    },
    "树与遍历": {
        "id": "tree-traversal",
        "name_en": "Trees & Traversal",
        "description": "二叉树、二叉搜索树、Trie、DFS、BFS、递归",
        "topics": [
            "Tree", "Binary Tree", "Binary Search Tree",
            "Trie", "Depth-First Search", "Breadth-First Search",
            "Recursion",
        ],
    },
    "堆与优先队列": {
        "id": "heap-queue",
        "name_en": "Heaps & Priority Queues",
        "description": "堆、优先队列、拓扑排序",
        "topics": [
            "Heap (Priority Queue)", "Topological Sort",
        ],
    },
    "图论": {
        "id": "graph",
        "name_en": "Graph Theory",
        "description": "图遍历、最短路径、欧拉回路、强连通分量、最小生成树",
        "topics": [
            "Graph", "Shortest Path", "Eulerian Circuit",
            "Strongly Connected Component", "Minimum Spanning Tree",
        ],
    },
    "动态规划": {
        "id": "dynamic-programming",
        "name_en": "Dynamic Programming",
        "description": "DP、记忆化搜索、状态压缩",
        "topics": [
            "Dynamic Programming", "Memoization", "Bitmask",
        ],
    },
    "贪心与排序": {
        "id": "greedy-sorting",
        "name_en": "Greedy & Sorting",
        "description": "贪心算法、各类排序算法",
        "topics": [
            "Greedy", "Sorting", "Merge Sort", "Bucket Sort",
            "Radix Sort", "Sort",
        ],
    },
    "二分与分治": {
        "id": "binary-search-divide",
        "name_en": "Binary Search & Divide and Conquer",
        "description": "二分查找、二分答案、分治算法",
        "topics": [
            "Binary Search", "Divide and Conquer",
        ],
    },
    "回溯与枚举": {
        "id": "backtracking",
        "name_en": "Backtracking & Enumeration",
        "description": "回溯、枚举、组合数学",
        "topics": [
            "Backtracking", "Enumeration", "Combinatorics",
        ],
    },
    "位运算": {
        "id": "bit-manipulation",
        "name_en": "Bit Manipulation",
        "description": "位操作技巧",
        "topics": [
            "Bit Manipulation",
        ],
    },
    "数学与几何": {
        "id": "math-geometry",
        "name_en": "Math & Geometry",
        "description": "数学、数论、几何、概率统计",
        "topics": [
            "Math", "Number Theory", "Geometry",
            "Probability and Statistics",
        ],
    },
    "并查集与线段树": {
        "id": "union-find-segtree",
        "name_en": "Union Find & Segment Trees",
        "description": "并查集、线段树、树状数组、滚动哈希",
        "topics": [
            "Union Find", "Segment Tree", "Binary Indexed Tree",
            "Rolling Hash",
        ],
    },
    "字符串匹配": {
        "id": "string-matching",
        "name_en": "String Matching",
        "description": "字符串匹配算法、后缀数组",
        "topics": [
            "String Matching", "Suffix Array",
        ],
    },
    "设计题": {
        "id": "design",
        "name_en": "System Design Problems",
        "description": "设计类题目、数据流、迭代器",
        "topics": [
            "Design", "Data Stream", "Iterator",
        ],
    },
    "其他专题": {
        "id": "other",
        "name_en": "Other Topics",
        "description": "数据库、并发、交互、随机化、博弈论、脑筋急转弯等",
        "topics": [
            "Database", "Concurrency", "Shell", "Interactive",
            "Randomized", "Game Theory", "Brainteaser",
            "Rejection Sampling", "Reservoir Sampling",
            "Ordered Set", "Line Sweep", "Quickselect",
        ],
    },
}


def build_leetcode_chapters() -> list[dict]:
    """从 LeetCode 数据构建章节列表（含问题统计）"""
    with open(LEETCODE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    problems = data.get("questions", [])

    # 统计每个 tag 的难度分布
    tag_difficulty = defaultdict(lambda: Counter())
    for p in problems:
        difficulty = p.get("difficulty", "Unknown")
        for tag in p.get("topics", []):
            tag_difficulty[tag][difficulty] += 1

    chapters = []
    for name_zh, info in LEETCODE_TAXONOMY.items():
        # 统计合并后的问题数（去重，一个题可能横跨多个 tag）
        topic_set = set(info["topics"])
        problem_ids = set()
        difficulty_dist = Counter()
        for p in problems:
            p_topics = set(p.get("topics", []))
            if p_topics & topic_set:
                pid = p.get("problem_id", p.get("frontend_id", ""))
                problem_ids.add(pid)
                difficulty_dist[p.get("difficulty", "Unknown")] += 1

        chapters.append({
            "id": f"lc-{info['id']}",
            "subject": "leetcode",
            "subject_zh": "算法与数据结构",
            "mode": "algorithm",
            "name_zh": name_zh,
            "name_en": info["name_en"],
            "description": info["description"],
            "topics": info["topics"],
            "problem_count": len(problem_ids),
            "difficulty_distribution": dict(difficulty_dist),
        })

    return chapters


# ====================================================================
# Part 3: 汇总输出
# ====================================================================

def main():
    print("=" * 60)
    print("Building chapters.json")
    print("=" * 60)

    # 1. CS-Base 章节
    cs_chapters = build_cs_chapters()
    total_cs_chars = sum(c["approx_chars"] for c in cs_chapters)
    print(f"\nCS-Base: {len(cs_chapters)} chapters, {total_cs_chars:,} total chars")
    for ch in cs_chapters:
        print(f"  [{ch['subject']}] {ch['name_zh']:12s}  "
              f"{ch['file_count']:2d} files  {ch['approx_chars']:>8,} chars")

    # 2. LeetCode 章节
    lc_chapters = build_leetcode_chapters()
    total_problems = sum(c["problem_count"] for c in lc_chapters)
    print(f"\nLeetCode: {len(lc_chapters)} chapters, {total_problems:,} unique problems")
    tag_count = sum(1 for c in lc_chapters for _ in c["topics"])
    print(f"  (from {tag_count} topic tags merged into {len(lc_chapters)} groups)")
    for ch in lc_chapters:
        diff = ch["difficulty_distribution"]
        print(f"  [{ch['id']}] {ch['name_zh']:14s}  "
              f"{ch['problem_count']:>5d} problems  "
              f"E:{diff.get('Easy', 0)} M:{diff.get('Medium', 0)} H:{diff.get('Hard', 0)}")

    # 3. 写入
    output = {
        "version": "1.0",
        "total_chapters": len(cs_chapters) + len(lc_chapters),
        "cs_fundamentals": cs_chapters,
        "algorithm": lc_chapters,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nWritten: {OUTPUT_FILE}")
    print(f"  {len(cs_chapters)} CS + {len(lc_chapters)} LC = {output['total_chapters']} total chapters")
    print("=" * 60)


if __name__ == "__main__":
    main()
