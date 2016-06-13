#!/usr/bin/env python
import sys
import argparse
import rospy

import baxter_interface
from baxter_interface import CHECK_VERSION
from hand_action import GripperClient
from arm_action import (computerIK, computerApproachPose)

from pa_localization.msg import pa_location
from birl_recorded_motions import paHome_rightArm as rh
from copy import copy
import PyKDL
import tf

import threading

class getPickingPose():
    def __init__(self):
        # Subscribe the pickingPose from pa_localization
        self._pose=pa_location()
        self._lock=threading.Lock()
        self._thread=threading.Thread(target=self.picking_location_listener)
        self._thread.start()

    def picking_location_listener(self):
        rospy.Subscriber("pick_location",pa_location,self.callback)
        rospy.spin()

    def callback(self,msg):
        self.lock()
        self._pose=msg
        self.unlock()

    def getPose(self):
        return self._pose

    def lock(self):
        self._lock.acquire()

    def unlock(self):
        self._lock.release()

def main():
    global reference_origin_pose_flag, reference_placing_pose_flag

    arg_fmt = argparse.RawDescriptionHelpFormatter # create ArgumentParser object
    parser = argparse.ArgumentParser(formatter_class=arg_fmt,
                                     description=main.__doc__)
    required = parser.add_argument_group('required arguments') # set required strings
    required.add_argument(
        '-l', '--limb', required=True, choices=['left', 'right'],
        help='send joint trajectory to which limb')
    args = parser.parse_args(rospy.myargv()[1:]) # return objects

    # Set limb and gripper side
    limb = args.limb
    ha=GripperClient(limb)

    pp_thread=getPickingPose()

    # get robot State
    print("Getting robot state...")
    rs=baxter_interface.RobotEnable(CHECK_VERSION)
    print("Enabling robot...")
    rs.enable()
    print("Running. Ctrl-c to quit")

    # Create Joint name list
    jNamesList=['right_s0','right_s1','right_e0','right_e1','right_w0','right_w1','right_w2']

    arm=baxter_interface.limb.Limb(limb)
    current_js=[arm.joint_angle(joint) for joint in arm.joint_names()]

    rospy.loginfo('Starting pa demo...')
    # Step 1, go to home position
    rospy.loginfo('I will first move to home position, and open the gripper...')
    rh.paHome_rightArm()
    ha.open()
    rospy.sleep(1.0)

    # Create kinematics method
    kin=computerIK(limb)
    cal_pose=computerApproachPose(limb)

    # Get Starting Position
    startPose=arm.endpoint_pose()
    startJoints=kin.calIK_PY_KDL(startPose)

    ############################
    x=  0.5697421207443628
    y= -0.3757602427005593
    z= -0.13873225259389357
    qx=-0.006904844072439628
    qy= 0.999853150657057
    qz= 0.0044387012368063035
    qw= 0.015043210455952832

    origin_p=baxter_interface.limb.Limb.Point(x,y,z)
    origin_q=baxter_interface.limb.Limb.Quaternion(qx,qy,qz,qw)
    origin_pose={'position':origin_p, 'orientation':origin_q}

    while not rospy.is_shutdown():

        # Put the male part on the table
        rospy.loginfo('Please put the male part on the table, and I will capture the location for picking')
        key=raw_input('When finished, press any key...')

        rospy.loginfo("waiting for picking pose from camera...")
        rospy.sleep(2.0)
        pp_thread.lock()
        picking_pose_visual=pp_thread.getPose()
        pp_thread.unlock()
        print(picking_pose_visual)

        ##############################
        #  pa_localization
        #    require: reference_origin_pose
        #    return:  picking_pose---{'position': picking_p, 'orientation': picking_q}
        ########################################################

        picking_pose=copy(origin_pose) # referring picking_pose from pa_localization to origin

        ref_x=copy(picking_pose['position'][0])
        ref_y=copy(picking_pose['position'][1])
        ref_z=copy(picking_pose['position'][2])

        ref_q=picking_pose['orientation']
        rot_mat=PyKDL.Rotation.Quaternion(ref_q.x,ref_q.y,ref_q.z,ref_q.w)
        rot_rpy=rot_mat.GetRPY()
        rot_rpy=list(rot_rpy)

        p_x=ref_x+picking_pose_visual.y
        p_y=ref_y+picking_pose_visual.x
        p_z=ref_z
        q=tf.transformations.quaternion_from_euler(rot_rpy[0],rot_rpy[1],rot_rpy[2]-picking_pose_visual.angle,axes='sxyz').tolist()
        picking_p=baxter_interface.limb.Limb.Point(p_x,p_y,p_z)
        picking_q=baxter_interface.limb.Limb.Quaternion(q[0],q[1],q[2],q[3])
        picking_pose={'position': picking_p, 'orientation': picking_q}

        #--------------- Picking Process -----------------------
        # Calculate ApproachPose
        approach_J_1,approach_J_2,pickingJoints=cal_pose.get_approach_joints_2(picking_pose,[0,0,0.05],[0,0,0.01])

        rospy.loginfo('Start picking...')
        arm.move_to_joint_positions(approach_J_1)
        rospy.sleep(1.0)
        print(arm.endpoint_pose())
        arm.move_to_joint_positions(approach_J_2)
        rospy.sleep(2.0)
        print(arm.endpoint_pose())
        arm.move_to_joint_positions(pickingJoints)
        rospy.sleep(2.0)
        print(arm.endpoint_pose())

        # close gripper
        ha.close()
        rospy.sleep(1.0)

        rospy.loginfo('Lift up...')
        arm.move_to_joint_positions(approach_J_2)
        rospy.sleep(1.0)
        arm.move_to_joint_positions(approach_J_1)
        rospy.sleep(1.0)

        ############################
        x=  0.5937780854021315
        y= 0.07366485118366262
        z= -0.12666281646935007
        qx=-0.0212788696557481
        qy= 0.9997232156282531
        qz= 0.005404221548422901
        qw= 0.008455544307423268
        ############################

        placing_p=baxter_interface.limb.Limb.Point(x,y,z)
        placing_q=baxter_interface.limb.Limb.Quaternion(qx,qy,qz,qw)
        placing_pose={'position':placing_p, 'orientation':placing_q}

        #--------------- Placing Process -----------------------
        # Calculate ApproachPose
        approach_J_1,approach_J_2,placingJoints=cal_pose.get_approach_joints_2(placing_pose,[0.0,0.0,0.05],[0.0,0.0,0.01])

        rospy.loginfo('Start placing...')
        arm.move_to_joint_positions(approach_J_1)
        rospy.sleep(1.0)
        print(arm.endpoint_pose())
        arm.move_to_joint_positions(approach_J_2)
        rospy.sleep(2.0)
        print(arm.endpoint_pose())
        arm.move_to_joint_positions(placingJoints)
        rospy.sleep(2.0)
        print(arm.endpoint_pose())

        # open gripper
        ha.open()
        rospy.sleep(1.0)

        ############################
        x=  0.5937780854021315
        y= 0.07366485118366262
        z= -0.12666281646935007
        qx=-0.0212788696557481
        qy= 0.9997232156282531
        qz= 0.005404221548422901
        qw= 0.008455544307423268
        ############################

        mid_p=baxter_interface.limb.Limb.Point(x,y,z)
        mid_q=baxter_interface.limb.Limb.Quaternion(qx,qy,qz,qw)
        mid_pose={'position':mid_p, 'orientation':mid_q}

        midJoints=kin.calIK_PY_KDL(mid_pose)
        arm.move_to_joint_positions(midJoints)
        rospy.sleep(2.0)
        print(arm.endpoint_pose())

        rospy.loginfo('Move to home position...')
        rh.paHome_rightArm()
        rospy.sleep(1.0)

if __name__ == "__main__":
    rospy.init_node("pa_manipulation")
    main()
