# CDC Design Guide (fixture)

## 3.1 CDC 定义

CDC（Clock Domain Crossing，跨时钟域）是指数字电路中信号从一个时钟域传递到另一个异步时钟域的过程。跨时钟域传输时，接收端触发器的建立/保持时间可能无法满足。

## 3.2 亚稳态原理

CDC 中产生亚稳态的主要原因是数据在接收时钟沿附近发生变化，导致触发器进入亚稳态。亚稳态会在后续逻辑中传播，造成功能失效。该机制与 MTBF 密切相关。

## 3.3 解决方案

单 bit 信号推荐使用双触发器同步器（Synchronizer）。多 bit 数据推荐 Handshake 或 Async FIFO。高速数据通路需要结合格雷码指针和复位策略。

## 3.4 设计约束

Synchronizer 必须放置在接收时钟域。需要计算 MTBF，并满足 Timing Constraint。禁止在 CDC 路径上直接对多 bit 总线做两级触发器同步。

## 3.5 示例

例如异步 FIFO 使用 Gray Code 编码读写指针，再通过同步器传递到对端时钟域，用于满/空检测。

## 3.6 例外

当两个时钟是同源且相位关系已知时，可以采用相位同步设计，而不使用异步 FIFO。该例外不适用于完全异步时钟。

## 5.2 Async FIFO Specification

异步 FIFO 架构包括写指针、读指针、指针同步、满检测、空检测和复位。指针必须使用 Gray Code。
