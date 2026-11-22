---
npcs:
  - id: npc_vendor
    template: person
    sheet:
      name: 卖花的老人
      fields: {appearance: 驼背，戴着褪色的棒球帽，推着花车, occupation: officer, str: 30, dex: 40, per: 70}
    location: {pos: {x: 20, y: -30, z: 0}}
  - id: npc_thief
    template: person
    sheet:
      name: 偷包裹的年轻人
      fields: {appearance: 灰色连帽衫，背着很大的黑色双肩包, occupation: reporter, str: 55, dex: 75, per: 45}
    location: {pos: {x: -60, y: 40, z: 0}}
initial_positions:
  courier: {pos: {x: 30, y: 10, z: 0}}
  student: {pos: {x: -20, y: -15, z: 0}}
  guard: {pos: {x: -80, y: 0, z: 0}}
  tourist: {pos: {x: 0, y: 30, z: 0}}
---
# KP 专属

## 真相
包裹是穿灰色连帽衫的年轻人（npc_thief）趁大屏幕黑屏时从快递员的推车上拿走的。他打算把包裹带到车站西侧，交给在商场停车场等他的人。包裹里只是一部旧手机，但手机里存着一段能证明某个店主欺诈的录音。

## NPC
- 卖花的老人（npc_vendor）：看见了年轻人往西走，但只会告诉对他态度好的人。
- 偷包裹的年轻人（npc_thief）：被叫住时会先装傻，被抓住手腕就会逃跑。

## 结局条件
- 包裹被找回：好结局。
- 年轻人进入商场停车场：包裹丢失，坏结局。
- 第 5 轮结束仍未解决：年轻人离开，坏结局。
