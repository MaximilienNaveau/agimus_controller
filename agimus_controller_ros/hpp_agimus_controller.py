#!/usr/bin/env python3
import rospy
import numpy as np
import time
from copy import deepcopy
from threading import Lock
from std_msgs.msg import Duration, Header
from linear_feedback_controller_msgs.msg import Control, Sensor

from agimus_controller.utils.ros_np_multiarray import to_multiarray_f64
from agimus_controller.utils.wrapper_panda import PandaWrapper
from agimus_controller.hpp_interface import HppInterface
from agimus_controller.mpc import MPC
from agimus_controller.ocps.ocp_croco_hpp import OCPCrocoHPP


class HppAgimusController:
    def __init__(self) -> None:
        self.dt = 0.05
        self.q_goal = [1.9542, -1.1679, -2.0741, -1.8046, 0.0149, 2.1971, 2.0056]
        self.horizon_size = 50

        self.pandawrapper = PandaWrapper(auto_col=False)
        self.rmodel, self.cmodel, self.vmodel = self.pandawrapper.create_robot()
        self.ee_frame_name = self.pandawrapper.get_ee_frame_name()
        self.hpp_interface = HppInterface()
        self.ocp = OCPCrocoHPP(self.rmodel, self.cmodel, use_constraints=False)
        self.ocp.set_weights(10**4, 1, 10**-3, 0)

        self.rate = rospy.Rate(100)
        self.mutex = Lock()
        self.sensor_msg = Sensor()
        self.control_msg = Control()
        self.ocp_solve_time = Duration()
        self.x0 = np.zeros(self.rmodel.nq + self.rmodel.nv)
        self.x_guess = np.zeros(self.rmodel.nq + self.rmodel.nv)
        self.u_guess = np.zeros(self.rmodel.nv)
        self.state_subscriber = rospy.Subscriber(
            "robot_sensors",
            Sensor,
            self.sensor_callback,
        )
        self.control_publisher = rospy.Publisher(
            "motion_server_control", Control, queue_size=1
        )
        self.ocp_solve_time_pub = rospy.Publisher(
            "ocp_solve_time", Duration, queue_size=1
        )
        self.start_time = 0.0
        self.first_solve = False
        self.first_robot_sensor_msg_received = False
        self.first_pose_ref_msg_received = True

    def sensor_callback(self, sensor_msg):
        with self.mutex:
            self.sensor_msg = deepcopy(sensor_msg)
            if not self.first_robot_sensor_msg_received:
                self.first_robot_sensor_msg_received = True

    def wait_first_sensor_msg(self):
        wait_for_input = True
        while not rospy.is_shutdown() and wait_for_input:
            wait_for_input = (
                not self.first_robot_sensor_msg_received
                or not self.first_pose_ref_msg_received
            )
            if wait_for_input:
                rospy.loginfo_throttle(3, "Waiting until we receive a sensor message.")
                with self.mutex:
                    sensor_msg = deepcopy(self.sensor_msg)
                    self.start_time = sensor_msg.header.stamp.to_sec()
            rospy.loginfo_once("Start controller")
            self.rate.sleep()
        return wait_for_input

    def plan_and_first_solve(self):
        sensor_msg = self.get_sensor_msg()

        # Plan
        q_init = [*sensor_msg.joint_state.position]
        self.ps = self.hpp_interface.get_panda_planner(q_init, self.q_goal)
        whole_x_plan, whole_a_plan, _ = self.hpp_interface.get_hpp_plan(
            self.dt,
            self.rmodel.nq,
            self.ps.client.problem.getPath(self.ps.numberPaths() - 1),
        )

        # First solve
        self.mpc = MPC(self.ocp, whole_x_plan, whole_a_plan, self.rmodel, self.cmodel)
        self.x_plan = self.mpc.whole_x_plan[: self.horizon_size, :]
        self.a_plan = self.mpc.whole_a_plan[: self.horizon_size, :]
        x0 = np.concatenate(
            [sensor_msg.joint_state.position, sensor_msg.joint_state.velocity]
        )
        self.mpc.mpc_first_step(self.x_plan, self.a_plan, x0, self.horizon_size)

        self.next_node_idx = self.horizon_size

    def solve_and_send(self):
        sensor_msg = self.get_sensor_msg()
        x0 = np.concatenate(
            [sensor_msg.joint_state.position, sensor_msg.joint_state.velocity]
        )

        new_x_ref = self.mpc.whole_x_plan[self.next_node_idx, :]
        new_a_ref = self.mpc.whole_a_plan[self.next_node_idx, :]

        mpc_duration = rospy.Time(time.time())
        self.mpc.mpc_step(x0, new_x_ref, new_a_ref)
        if self.next_node_idx < self.mpc.whole_x_plan.shape[0] - 1:
            self.next_node_idx += 1
        _, u, k = self.mpc.get_mpc_output()
        mpc_duration = rospy.Time(time.time()) - mpc_duration
        rospy.loginfo(1, "mpc_duration = %s", str(mpc_duration.to_sec()))

        self.control_msg.header = Header()
        self.control_msg.header.stamp = rospy.Time(time.time())
        self.control_msg.feedback_gain = to_multiarray_f64(k)
        self.control_msg.feedforward = to_multiarray_f64(u)
        self.control_msg.initial_state = sensor_msg
        self.control_publisher.publish(self.control_msg)

    def get_sensor_msg(self):
        with self.mutex:
            sensor_msg = deepcopy(self.sensor_msg)
        return sensor_msg

    def run(self):
        self.wait_first_sensor_msg()
        self.plan_and_first_solve()
        input("Press Enter to continue...")
        while not rospy.is_shutdown():
            start_compute_time = rospy.Time.now()
            self.solve_and_send()
            self.ocp_solve_time.data = rospy.Time.now() - start_compute_time
            self.ocp_solve_time_pub.publish(self.ocp_solve_time)
            self.rate.sleep()


def crocco_motion_server_node():
    rospy.init_node("croccodyl_motion_server_node_py", anonymous=True)
    node = HppAgimusController()
    node.run()


if __name__ == "__main__":
    try:
        crocco_motion_server_node()
    except rospy.ROSInterruptException:
        pass
