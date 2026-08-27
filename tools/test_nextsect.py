# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"e:\DS\mhxy-gui-automation")
from library.map_packs import MPCG as M

tests = {
    "guard下一关": "你通过了本门派护法的考验，请继续前往下一关#Y/盘丝洞#W/接受考验。",
    "accept": "你成功领取了门派闯关任务，请立即前往#Y/女儿村#W/接受考验。",
    "会员卡福利": "尊贵的会员玩家，你可以每天在我这边领取一次福利，达到相应等级也可以获取相应福利！#Y/（每日福利随机抽奖物品有：#R/高级宝图、高级兽决",
    "完成": "恭喜你们完成了本轮门派闯关活动",
    "intro阴曹": "门派闯关活动，请立即前往阴曹地府接受门派护法考验，已成功完成了0次考验。",
}
for k, v in tests.items():
    print(k, "=>", repr(M._next_sect(v)))
print("intro_target:", M._intro_target("请立即前往阴曹地府"), "| count(3):", M._intro_count("已成功完成了3次考验"))