name: Pull Request
description: 提交代码更改
title: "[PR] "

body:
  - type: markdown
    attributes:
      value: |
        感谢贡献！请填写以下内容帮助我们审查你的更改。

  - type: textarea
    id: description
    attributes:
      label: 描述
      description: 这个 PR 做了什么？
      placeholder: "例如：修复了订阅续费时的日期计算错误..."
    validations:
      required: true

  - type: textarea
    id: related_issue
    attributes:
      label: 相关 Issue
      description: 这个 PR 关联的 Issue（如 #123）
      placeholder: "例如：Closes #123"

  - type: dropdown
    id: type
    attributes:
      label: 更改类型
      options:
        - Bug 修复
        - 新功能
        - 文档更新
        - 代码重构
        - 性能优化
        - 其他
    validations:
      required: true

  - type: textarea
    id: testing
    attributes:
      label: 测试
      description: 说明如何测试这个更改
      placeholder: |
        - 运行了本地测试
        - 在 Docker 中测试过
        - 等等...
    validations:
      required: true

  - type: checkboxes
    id: checklist
    attributes:
      label: 检查清单
      options:
        - label: 我的代码遵循项目的代码风格
          required: true
        - label: 我自行审查了自己的代码
          required: true
        - label: 我添加了必要的注释和文档
          required: true
        - label: 我的更改没有产生新的警告
          required: true
        - label: 我在本地测试了这个更改
          required: true
