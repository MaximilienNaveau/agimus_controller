#!/usr/bin/env python

from agimus_controller.mpc import MPC
from agimus_controller.hpp_interface import HppInterface
from agimus_controller.plots import MPCPlots
from agimus_controller.ocp_croco_hpp import OCPCrocoHPP
import time


if __name__ == "__main__":
    hpp_interface = HppInterface()
    ps = hpp_interface.ps
    vf = hpp_interface.vf
    ball_init_pose = [-0.2, 0, 0.02, 0, 0, 0, 1]
    hpp_interface.get_hpp_plan(1e-2, 6)
    ocp = OCPCrocoHPP("ur5")
    mpc = MPC()
    start = time.time()
    mpc.initialize(ocp, hpp_interface.x_plan, hpp_interface.a_plan)
    mpc.prob.set_costs(10**4, 1, 10**-3, 0, 0)
    # mpc.search_best_costs(mpc.prob.nb_paths - 1, False, False, True)
    mpc.do_mpc(100)
    end = time.time()
    u_plan = mpc.prob.get_uref(hpp_interface.x_plan, hpp_interface.a_plan)
    mpc_plots = MPCPlots(
        mpc.croco_xs,
        mpc.croco_us,
        hpp_interface.x_plan,
        u_plan,
        mpc.robot,
        vf,
        ball_init_pose,
        mpc.prob.DT,
    )
    print("mpc duration ", end - start)
    mpc_plots.display_path()
