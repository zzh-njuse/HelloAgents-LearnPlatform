---
name: leetcode-patterns
description: 算法解题模式分类：双指针、滑动窗口、动态规划、树遍历、图搜索的识别特征和模板代码
---

# 算法解题模式

## 1. 双指针 (Two Pointers)

### 识别特征
- 有序数组或链表
- 找一对元素满足条件（两数之和、三数之和）
- 原地修改数组（去重、移动零）

### 模板
```python
def two_pointers(arr):
    left, right = 0, len(arr) - 1
    while left < right:
        current = arr[left] + arr[right]  # 或其他操作
        if current == target:
            return [left, right]
        elif current < target:
            left += 1
        else:
            right -= 1
    return []
```

### 经典题
- LC 167: Two Sum II (有序数组)
- LC 15: 3Sum
- LC 11: Container With Most Water

## 2. 滑动窗口 (Sliding Window)

### 识别特征
- 子数组/子串问题
- 要求连续
- "最长/最短的子X包含Y"

### 模板
```python
def sliding_window(s):
    window = {}
    left, right = 0, 0
    while right < len(s):
        c = s[right]
        window[c] = window.get(c, 0) + 1
        right += 1
        
        while 窗口需要收缩:
            d = s[left]
            window[d] -= 1
            left += 1
    return result
```

### 经典题
- LC 3: Longest Substring Without Repeating Characters
- LC 76: Minimum Window Substring
- LC 438: Find All Anagrams in a String

## 3. 动态规划 (Dynamic Programming)

### 识别特征
- "最值"问题（最大、最小、最长、最短）
- "方案数"问题（多少种方法）
- 问题可分解为重叠子问题，有最优子结构

### 解题五步法
1. 定义 dp[i] 的含义
2. 找状态转移方程
3. 确定 base case（初始值）
4. 确定遍历顺序
5. 尝试空间优化

### 模板
```python
def dp_template(nums):
    n = len(nums)
    dp = [0] * n
    dp[0] = base_case
    
    for i in range(1, n):
        dp[i] = f(dp[i-1], nums[i])  # 状态转移
    
    return dp[-1]  # 或 max(dp)
```

### 经典题
- LC 53: Maximum Subarray
- LC 300: Longest Increasing Subsequence
- LC 1143: Longest Common Subsequence
- LC 322: Coin Change
- LC 416: Partition Equal Subset Sum (0/1 背包)

## 4. 二叉树遍历 (Tree Traversal)

### 识别特征
- 树形结构问题
- "前/中/后序遍历"、"层序遍历"
- "路径"、"深度"、"高度"

### DFS 模板
```python
def dfs(root):
    if not root:
        return
    # 前序: process(root)
    dfs(root.left)
    # 中序: process(root)
    dfs(root.right)
    # 后序: process(root)
```

### BFS 模板
```python
from collections import deque
def bfs(root):
    q = deque([root])
    while q:
        level_size = len(q)
        for _ in range(level_size):
            node = q.popleft()
            process(node)
            if node.left: q.append(node.left)
            if node.right: q.append(node.right)
```

### 经典题
- LC 104: Maximum Depth of Binary Tree
- LC 236: Lowest Common Ancestor
- LC 102: Binary Tree Level Order Traversal

## 5. 二分查找 (Binary Search)

### 识别特征
- 有序数据
- "查找"、"搜索"
- O(log n) 时间要求

### 模板
```python
def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = left + (right - left) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
```

### 经典题
- LC 704: Binary Search
- LC 33: Search in Rotated Sorted Array
- LC 69: Sqrt(x)

## 常见错误

1. **双指针忘记更新**: 只移动一个指针导致死循环
2. **滑动窗口不收缩**: left 从不前进，窗口越来越大
3. **DP 数组大小**: 搞混 n 和 n+1
4. **树遍历忘记 base case**: 没有 if not root 导致空指针
5. **二分查找死循环**: mid 计算溢出或边界更新错误
