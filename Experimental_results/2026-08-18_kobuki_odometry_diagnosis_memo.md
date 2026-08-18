# 2026年8月18日 Kobuki ODOM診断メモ

## 1. 結論

初期設定`use_imu_heading=true`の`/odom`は、Kobukiの実際の運動を表す基準値として使用できなかった。比較試験で`use_imu_heading=false`へ変更すると、車輪ODOMによる旋回角速度が復元し、その場旋回中の並進速度もほぼ0だった。Yawと`angular.z`が0だった直接原因は、旋回に追従しないIMU headingを車輪ODOMへ強制適用していたことだと判断する。

その場回転中にも`twist.twist.angular.z`と`pose.pose.orientation`が変化せず、代わりに`twist.twist.linear.x`が変化した。このまま`bird_eye.py`へ入力すると、その場回転を直進として扱い、経路予測、相対速度、TTC、衝突候補判定を誤る。

`/joint_states`では前進時に左右が同符号、その場回転時に逆符号となっており、車輪ODOMの入力は正常だった。`use_imu_heading=false`で右旋回、左旋回、前進、後退の符号もすべて正常になった。既存ドライバには車輪ODOM機能があるため、独立ブリッジの新規実装は現時点で不要である。次は停止時ノイズ、TFのYaw、直進距離、360度旋回角を検証し、残留する並進・角速度誤差を含めて実験基準として正式採用できるか判定する。

動的TTC試験と旋回経路試験は、車輪ODOMの符号・距離・角度校正が完了するまで保留する。停止状態の位置精度試験と遮蔽試験は実施可能である。

## 2. 確認環境

- 確認日: 2026年8月18日
- ROS 2ノード: `/kobuki`
- ODOMトピック: `/odom`
- ODOM型: `nav_msgs/msg/Odometry`
- Publisher: `/kobuki`の1ノードのみ
- `base_frame`: `base_footprint`
- `odom_frame`: `odom`
- `publish_tf`: `true`
- `use_imu_heading`: `true`
- 左車輪設定名: `wheel_left_joint`
- 右車輪設定名: `wheel_right_joint`

`ros2 pkg prefix kobuki_node`は`Package not found`となった。ノード名とROSパッケージ名は同一とは限らないため、使用パッケージは別途`ros2 pkg executables`で特定する。

## 3. 測定事実

### 3.1 `/odom`のPublisher

`ros2 topic info /odom -v`の結果:

- Publisher count: 1
- Node name: `kobuki`
- Reliability: RELIABLE
- Durability: VOLATILE

複数Publisherの競合はない。

### 3.2 `/odom`の運動値

実機を前進、後退、その場回転させて確認した結果:

- `pose.pose.orientation`: その場回転中も変化なし
- `twist.twist.angular.z`: その場回転中も0
- `twist.twist.linear.x`: 前進、後退、旋回のすべてで変化

したがって、`bird_eye.py`側のフィールド読取り違いではなく、受信している`/odom`メッセージ自体が標準的な差動二輪ODOMの意味を満たしていない。

### 3.3 録画データ

録画:

`/home/hsr/Downloads/recoding/preflight_odom_motion_20260818_124306_249`

| 項目 | 結果 |
|---|---:|
| CSV・各動画フレーム | 809フレームで一致 |
| 実時間 | 32.32353秒 |
| 実効FPS | 24.997 fps |
| ODOM有効率 | 100% |
| 記録`linear.x`範囲 | -0.036249～+0.089557 m/s |
| 記録`angular.z`範囲 | 0～0 rad/s |
| CSV列数 | 全行42列 |
| NUL混入 | 0 |

この録画では実際にはその場回転していたため、`linear.x > 0`の区間を前進として扱った当初判定を撤回する。録画ファイルの完全性は合格だが、運動意味の判定は不合格である。

### 3.4 `/joint_states`

その場回転中の`velocity`例:

```text
[+2.4369168, -2.1932251]
[+2.4369168, -2.4369168]
[+2.1932251, -2.3150710]
```

2要素が逆方向に変化しており、その場回転の車輪運動は取得できている。ただし、配列の並び順と各車輪の正方向は`name`と前進試験を用いて確認する必要がある。

### 3.5 IMU

`/imu`は発行されていない。`/kobuki`が実際に発行しているIMUトピックは次の2つである。

- `/sensors/imu_data`
- `/sensors/imu_data_raw`

`/imu`に対する確認失敗はセンサー不在を意味せず、トピック名の不一致である。

### 3.6 追加確認（2026年8月18日）

停止状態で取得した`/joint_states`の完全なメッセージから、配列の対応を確認した。

| 配列番号 | `name` | 停止時`velocity` |
|---:|---|---:|
| 0 | `wheel_left_joint` | 0.0 |
| 1 | `wheel_right_joint` | 0.0 |

これにより、先に記録した旋回時の例は左車輪、右車輪の順であると確定した。今回の`--once`は停止中の取得なので、両速度が0であることは正常であり、車輪情報の異常を示さない。

その場回転中に`/sensors/imu_data`の`angular_velocity`を監視したが、値は変化しなかった。したがって、現時点ではこのfused IMUトピックを旋回角速度の供給元にできない。メッセージ更新自体の有無と`/sensors/imu_data_raw`の生値を追加確認する。

### 3.7 生IMUと前進時車輪速度（2026年8月18日）

`/sensors/imu_data_raw`の`angular_velocity`では、次のような値が取得された。

```text
x: -0.0131 ～ -0.0086 rad/s
y: -0.0316 ～ -0.0293 rad/s
z: -0.0047 ～ -0.0008 rad/s
```

値は完全な固定値ではないが、提示区間の`z`はほぼ0付近の小さな変動に留まっている。実施時の旋回方向、旋回速度、停止時基準値が一緒に記録されていないため、この結果だけでIMUの使用可否は最終確定しない。ただし、少なくとも今回の値から旋回を明瞭に識別できておらず、現段階では実験用角速度の第一候補にしない。

低速前進時の`/joint_states.velocity`は、配列順`[wheel_left_joint, wheel_right_joint]`で次のように観測された。

```text
[+2.4369, +2.6806]
[+2.8025, +2.6806]
[+2.5588, +2.1932]
[+2.4369, +2.3151]
[+2.4369, +2.6806]
[+2.4369, +2.5588]
[+2.5588, +2.5588]
```

前進時は左右とも正、その場回転時は左右が逆符号になることを確認できた。この符号規則なら、左右車輪速度の和から並進速度、差から角速度を区別して計算できる。

公称車輪半径を仮に`0.035 m`として今回の前進値を換算すると、代表的な並進速度は約`0.087 m/s`となり、録画CSVで観測された`/odom.linear.x`最大値`0.089557 m/s`とも概ね整合する。ただし、最終実装では使用中ドライバまたは実機仕様から車輪半径と車輪間隔を確定する。

### 3.8 TFと実行パッケージ（2026年8月18日）

`/odom.child_frame_id`は`base_footprint`だった。実機をその場旋回させながら`odom -> base_footprint`のTFを監視した結果、全サンプルで次の状態だった。

```text
Quaternion (xyzw): [0.000, 0.000, 0.000, 1.000]
RPY yaw: 0.000 rad / 0.000 deg
Translation y: 0.000 m
Translation x: 0.536 -> 0.354 -> 0.444 m などと変化
```

起動直後に一度だけ`frame does not exist`が出たが、その後はTFを継続受信できているため、主問題はTF未配信ではない。その場旋回中にもYawは常に0で、代わりにX並進が変化している。したがって、TFは`/odom`と同じ誤った運動解釈を反映しており、角速度または姿勢の代替情報源にはできない。

パッケージ検索結果は次のとおりだった。

```text
ros2 pkg executables | grep -i kobuki
kobuki_velocity_smoother velocity_smoother

ros2 pkg prefix kobuki
Package not found
```

現在sourceされているROS 2環境のament indexでは、`/kobuki`を提供する`kobuki`パッケージを特定できない。ノードは動作しているため、別ワークスペースの未source環境、ROSパッケージ外の直接起動、または別名パッケージから実行されている可能性がある。プロセスの実行コマンドと実体パスをOS側から特定する必要がある。

OSプロセスを確認した結果、`/kobuki`ノード本体は次の実行ファイルだと判明した。

```text
PID 72078
/home/matunuc/kobuki_ws/install/kobuki_node/lib/kobuki_node/kobuki_ros_node
  --ros-args
  -r __node:=kobuki
  --params-file /tmp/launch_params_5dmykgk5
  -r /commands/velocity:=/cmd_vel
```

起動経路は次のとおりである。

```text
start_kobuki_ffb.sh
  -> ros2 launch oit kobuki_vehicle_launch.py
  -> kobuki_node/kobuki_ros_node
```

したがって、実行元は`~/kobuki_ws`のローカルビルドである。先の`ros2 pkg prefix kobuki_node`失敗は、診断を行ったシェルで`~/kobuki_ws/install/setup.bash`がsourceされていなかった可能性が高い。次は同ワークスペースをsourceした環境でパッケージ情報を確認し、`~/kobuki_ws/src`のODOM演算実装を調べる。

### 3.9 ODOMソース位置（2026年8月18日）

overlayをsourceしたシェルでは、パッケージと実行ファイルを正常に確認できた。

```text
package prefix: /home/matunuc/kobuki_ws/install/kobuki_node
executable: kobuki_node kobuki_ros_node
```

ODOMの主要な処理位置は次の3か所である。

| 処理 | ソース |
|---|---|
| エンコーダ・ジャイロからODOM更新量を算出 | `turtlebot2_ros2/kobuki_core/src/driver/kobuki.cpp` 484行付近 |
| ODOMとJointStateの更新・publish | `turtlebot2_ros2/kobuki_ros/kobuki_node/src/kobuki_ros.cpp` 592行付近 |
| ROS Odometryメッセージへの格納 | `turtlebot2_ros2/kobuki_ros/kobuki_node/src/odometry.cpp` 149～151行 |

ROSメッセージへの格納処理は検索結果上、次の標準的な対応になっている。

```cpp
odom->twist.twist.linear.x = pose_update_rates_[0];
odom->twist.twist.linear.y = pose_update_rates_[1];
odom->twist.twist.angular.z = pose_update_rates_[2];
```

この代入だけを見る限り、`linear.x`と`angular.z`の入れ替えではない。問題は`pose_update_rates_`の生成・更新、またはその入力となる`kobuki_core`側のODOM更新量にある可能性が高い。断定には各関数本体の確認が必要である。

### 3.10 `use_imu_heading`による上書き（2026年8月18日）

`kobuki_core`の`Kobuki::updateOdometry()`は、エンコーダ値をそのまま`diff_drive.update()`へ渡している。

```cpp
diff_drive.update(
  core_sensors.data.time_stamp,
  core_sensors.data.left_encoder,
  core_sensors.data.right_encoder,
  pose_update,
  pose_update_rates
);
```

その後、`kobuki_node`の`Odometry::update()`では次の処理を行っている。

```cpp
ecl::extend_pose(pose_, pose_update);

if (use_imu_heading_) {
  pose_[2] = ecl::wrap_angle(imu_heading);
  pose_update_rates[2] = imu_angular_velocity;
}
```

現在の設定は`use_imu_heading: true`である。したがって、`diff_drive.update()`が車輪から正しいYaw更新量と角速度を算出していても、最終的なYawは`kobuki_.getHeading()`、`angular.z`は`kobuki_.getAngularVelocity()`で必ず上書きされる。

実機ではfused IMUの角速度と姿勢が旋回に追従せず、生IMUの`z`もほぼ0付近だった。この組合せにより、次の2症状はソース上でも説明できる。

- `/odom.pose.pose.orientation`とTFのYawが常に0
- `/odom.twist.twist.angular.z`が常に0

よって、Yawと`angular.z`が0になる直接原因は、無効なIMU値を`use_imu_heading=true`で車輪ODOMへ強制適用していることである。

ただし、この上書き処理は`pose_update_rates[0]`と並進量`pose_update[0]`を変更していない。その場旋回中に`linear.x`とTFのX並進が大きく変化する問題は別に残っており、`diff_drive.update()`内部の左右エンコーダ処理を確認する必要がある。

### 3.11 `DiffDrive::update()`実装位置（2026年8月18日）

検索により、車輪ODOM計算の実体を次のファイルへ特定した。

```text
/home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_core/src/driver/diff_drive.cpp
```

主要箇所は次のとおりである。

- 25行付近: `DiffDrive`コンストラクタと車輪寸法・変換係数
- 51行付近: `DiffDrive::update()`開始
- 86行付近: `poseUpdateFromWheelDifferential()`呼出し
- 101行付近: `pose_update_rates`生成
- 116行付近: JointStateの角度・角速度取得

このファイルの1～115行を確認すれば、左右エンコーダ差分の型と符号、tickから車輪角度への変換、並進・旋回更新量、更新時間の計算を一続きで検証できる。

### 3.12 `DiffDrive::update()`内容と公式実装比較（2026年8月18日）

ローカル実装では次の定数を使用している。

| 項目 | 値 |
|---|---:|
| 車輪間隔 `bias` | 0.23 m |
| 車輪半径 | 0.035 m |
| encoder tick→rad | 0.00243691687136 rad/tick |

エンコーダ差分は次の式で16bitの折返し後に符号付き`short`へ変換されており、前進・後退の符号を失う単純なunsigned演算にはなっていない。

```cpp
left_diff_ticks = (double)(short)((curr_tick_left - last_tick_left) & 0xffff);
right_diff_ticks = (double)(short)((curr_tick_right - last_tick_right) & 0xffff);
```

車輪差分から姿勢更新を生成し、その3要素を時間差で割っている。

```cpp
pose_update = diff_drive_kinematics.poseUpdateFromWheelDifferential(
  tick_to_rad * left_diff_ticks,
  tick_to_rad * right_diff_ticks
);

pose_update_rates << pose_update[0] / last_diff_time,
                     pose_update[1] / last_diff_time,
                     pose_update[2] / last_diff_time;
```

公式の旧Kobuki実装も、同じ車輪寸法、tick変換、符号付きエンコーダ差分を使用している。一方、旧実装は戻り値が`LegacyPose2D`であり、速度格納時に`.x()`、`.y()`、`.heading()`を明示していた。ローカルROS 2移植版は`Vector3d`と`poseUpdateFromWheelDifferential()`へ変更され、添字0、1、2をそれぞれx、y、headingと解釈している。

この差分は調査対象だが、現時点ではECL APIの戻り値順序が誤っているとは断定できない。エンコーダ差分処理にも明白な誤りは見つからなかった。先に確定している不具合は、無効なIMUを`use_imu_heading=true`でYawと角速度へ強制適用している点である。

参考:

- [公式Kobuki `diff_drive.cpp`ソース](https://yujinrobot.github.io/kobuki/diff__drive_8cpp_source.html)
- [ROS 2 Humble ECL DifferentialDrive API](https://docs.ros.org/en/humble/p/ecl_mobile_robot/generated/program_listing_file_include_ecl_mobile_robot_kinematics_differential_drive.hpp.html)

### 3.13 `use_imu_heading`設定経路（2026年8月18日）

ソース検索により、設定候補とコード上の読込み経路を確認した。

```text
kobuki_node/config/kobuki_node_params.yaml: use_imu_heading: true
kobuki_auto_docking/config/kobuki_node_params.yaml: use_imu_heading: true
kobuki_ros.cpp: declare_parameter("use_imu_heading", true)
kobuki_ros.cpp: Odometry(..., use_imu_heading, ...)
odometry.cpp: use_imu_heading_(use_imu_heading)
```

この値はノード初期化時にparameterから読み、`Odometry`のコンストラクタへ渡してメンバー変数へ保持している。確認した範囲には動的parameter変更のcallbackがないため、実行中に`ros2 param set`するだけでは既存`Odometry`インスタンスへ反映されない。実際にlaunchが使用する設定を`false`へ変更し、ノードを再起動する必要がある。

設定ファイル候補が2つあり、launchがparameterを渡さない場合はコード既定値`true`も使われ得る。変更対象を誤らないため、先に`oit/kobuki_vehicle_launch.py`から`kobuki_ros_node`へのparameter指定を確認する。

### 3.14 実使用launchの絞り込み（2026年8月18日）

launch検索の結果、標準`kobuki_node`パッケージには`kobuki_node_params.yaml`を読み込むlaunchが存在する一方、現在の実機プロセスはFFBワークスペース内の`oit`パッケージから起動されている。

実プロセスで確認済みの起動コマンド:

```text
ros2 launch oit kobuki_vehicle_launch.py
```

対応するソース候補:

```text
/home/matunuc/ffb/src/FFB_feedback_control/src/oit/launch/kobuki_vehicle_launch.py
/home/matunuc/ffb/src/FFB_feedback_control/src/oit/launch/kobuki_launch.py
```

インストール後に実際に`ros2 launch`が参照する候補:

```text
/home/matunuc/ffb/install/oit/share/oit/launch/kobuki_vehicle_launch.py
/home/matunuc/ffb/install/oit/share/oit/launch/kobuki_launch.py
```

検索結果では`kobuki_vehicle_launch.py`のparameter指定はtwist muxとwatchdogに対応しており、`use_imu_heading`の直接指定は見つからなかった。`kobuki_ros_node`の生成または別launchのinclude方法を確認するまで、標準YAMLを変更対象と断定しない。

### 3.15 実使用parameterファイルの確定（2026年8月18日）

FFB側の`kobuki_vehicle_launch.py`は、次の処理で`kobuki_node`パッケージの公式launchをincludeしている。

```python
kobuki_node_dir = get_package_share_directory('kobuki_node')
kobuki_launch = IncludeLaunchDescription(
    PythonLaunchDescriptionSource(
        os.path.join(kobuki_node_dir, 'launch', 'kobuki_node-launch.py')
    )
)
```

公式`kobuki_node-launch.py`は、同パッケージの`config/kobuki_node_params.yaml`を読み込むことを検索結果で確認済みである。したがって、現在の起動経路は次のとおりである。

```text
oit/kobuki_vehicle_launch.py
  -> kobuki_node/launch/kobuki_node-launch.py
  -> kobuki_node/config/kobuki_node_params.yaml
  -> kobuki_ros_node
```

比較試験で変更するソース側ファイルは次である。

```text
/home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_ros/kobuki_node/config/kobuki_node_params.yaml
```

`kobuki_auto_docking/config/kobuki_node_params.yaml`は現在の起動経路ではないため変更しない。また、FFB側`kobuki_vehicle_launch.py`のsource版とinstall版は提示範囲で一致していた。

### 3.16 `use_imu_heading=false`比較結果（2026年8月18日）

次の実使用parameterを`true`から`false`へ変更し、Kobukiノードを再起動した。

```text
/home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_ros/kobuki_node/config/kobuki_node_params.yaml
```

起動後のparameter確認:

```text
ros2 param get /kobuki use_imu_heading
Boolean value is: False
```

その場旋回中の`/odom.twist.twist`では次の範囲を観測した。

| 項目 | 観測範囲 |
|---|---:|
| `linear.x` | 0.0000～0.0042646 m/s |
| `linear.y` | 0 m/s |
| `angular.z` | -0.57479～-0.55625 rad/s |

変更前の試験ではその場旋回中に大きなX並進を出力し、`angular.z`が常に0だった。変更後の試験では並進がほぼ0となり、明瞭な旋回角速度が得られた。最大残留並進約4.3 mm/sは小さく、少なくとも今回の試験では旋回を正しく区別できている。

ただし、ソース上で`use_imu_heading`が直接上書きするのはYawと`pose_update_rates[2]`であり、`pose_update_rates[0]`ではない。したがって、変更前に観測した大きな`linear.x`まで同parameterだけが原因だとは断定しない。同じ速度指令・同じ操作手順で左右旋回と前進を再測定し、再現性を確認する。

提示されたデータは一方向の旋回区間で、実際の旋回方向との対応が記録されていない。よって、左右旋回時の`angular.z`符号と前進・後退時の`linear.x`符号は追加確認する。

### 3.17 右旋回・左旋回・前進・後退の符号確認（2026年8月18日）

`use_imu_heading=false`を維持し、4種類の運動で`/odom.twist.twist`を確認した。この試験は後から、keyopではなく人が機体を直接動かしたものだと判明した。

| 実運動 | `linear.x` [m/s] | `angular.z` [rad/s] | 符号判定 |
|---|---:|---:|---|
| 右旋回 | -0.01919、-0.01706 | -0.16688、-0.14833 | PASS |
| 左旋回 | -0.01706 | +0.51917 | PASS |
| 前進 | +0.08956、+0.09595 | +0.03708、-0.01854 | PASS |
| 後退 | -0.08956、-0.09382 | 0.00000、-0.03708 | PASS |

運動方向と符号の関係はすべてROSの平面移動規約と一致した。

- 右旋回: `angular.z < 0`
- 左旋回: `angular.z > 0`
- 前進: `linear.x > 0`
- 後退: `linear.x < 0`

よって、運動種別と方向を識別する参考結果としては合格とする。

純旋回時に約`-0.017～-0.019 m/s`の後退成分、直進・後退時に最大約`0.037 rad/s`の角速度残差が観測された。ただし、手で直接動かした場合は左右車輪へ均等な力を与えられず、キャスターや床面の力も加わるため、この値を車輪ODOM精度の定量評価には使用しない。

停止時データとTF Yawの追従確認は未完了である。

### 3.18 keyopによる4方向再試験（2026年8月18日）

手押しの影響を除くため、kobuki keyopで前進、後退、右回転、左回転を行い、`/odom.twist.twist`を再確認した。

| keyop運動 | `linear.x` [m/s] | `angular.z` [rad/s] | 判定 |
|---|---:|---:|---|
| 前進 | +0.08742～+0.08956 | -0.01854～0.00000 | PASS |
| 後退 | -0.07676 | 0.00000～+0.03708 | PASS |
| 右回転 | -0.00426～+0.00426 | -0.55625～-0.48209 | PASS |
| 左回転 | -0.00213～+0.00213 | +0.94563～+1.05688 | PASS |

keyop試験でも4方向すべての符号が正しい。純旋回中の`abs(linear.x)`は最大`0.0042646 m/s`であり、手押し試験の約`0.019 m/s`から大幅に低下した。直進・後退中の角速度残差は最大`0.03708 rad/s`だが、多くのサンプルは0または`0.01854 rad/s`程度である。

したがって、車輪ODOMは少なくとも運動種別、方向、直進と旋回の分離について合格とする。左右旋回の角速度絶対値は異なるが、keyopの指令角速度が同一だった記録がないため、現時点では左右ODOM誤差とは判定しない。直進距離と360度旋回による絶対精度評価は引き続き必要である。

### 3.19 TF追従と1 m直進精度（2026年8月18日）

#### 停止時のTF安定性

約11秒間の停止区間では、TFが次の値で固定されていた。

```text
Translation: [-0.025, -0.285, 0.000] m
Yaw: 11.091 deg
```

表示分解能内で位置・Yawのドリフトはなく、停止時の姿勢安定性はPASSとする。`twist`の10秒最大値は別途直接記録していないが、少なくとも積算姿勢の静止ドリフトは確認されなかった。

#### TFの左右旋回追従

左方向の旋回ではYawが`11.091 -> 177.776 -> -154.199 -> -78.962 deg`と増加し、±180度で正常にwrapした。その後の逆方向旋回では`-79.769 -> -146.210 -> 166.090 -> 114.523 -> 20.185 -> -52.736 deg`と反対方向へ変化した。

したがって、TFは左右旋回へ追従し、符号と角度wrapも正常である。TF Yaw追従はPASSとする。旋回中の並進変化は約1 cm規模だった。

#### 1 m直進試験

各試行の開始Poseと終了Poseの差から2次元移動距離を計算した。開始Yawが0ではなかったため、最終`x`だけでなく次式を使用した。

```text
dx = x_end - x_start
dy = y_end - y_start
distance = sqrt(dx^2 + dy^2)
```

横ずれは開始Yawを基準とするローカル横方向へ変位を射影して求めた。

| 試行 | 2次元距離 [m] | 距離誤差 [cm] | 横ずれ [cm] | Yaw変化 [deg] |
|---:|---:|---:|---:|---:|
| 1 | 0.998133 | -0.187 | -1.850 | -1.742 |
| 2 | 1.014885 | +1.489 | -2.104 | -1.934 |
| 3 | 1.006405 | +0.641 | -2.046 | -2.040 |

集計:

| 指標 | 結果 | 暫定条件 | 判定 |
|---|---:|---:|---|
| 距離MAE | 0.772 cm | 5 cm以下 | PASS |
| 最大絶対距離誤差 | 1.489 cm | 8 cm以下 | PASS |
| 最大絶対横ずれ | 2.104 cm | 5 cm以下 | PASS |
| 1 m当たりYaw変化 | 1.742～2.040 deg | 探索値 | 記録 |

車輪半径`0.035 m`による直進距離スケールは十分正確であり、現時点で変更しない。各試行の開始Poseが原点ではなかったため、今後の校正ではreset後に開始Poseがほぼ0であることも確認する。

### 3.20 左右360度旋回精度（2026年8月18日）

床上で物理的に360度旋回して開始方向へ戻し、停止後のTF Yawを左右各3回記録した。

| 試行 | 方向 | 停止時Yaw [deg] | 絶対残差 [deg] | 中心並進量の概算 [cm] |
|---:|---|---:|---:|---:|
| 1 | 左 | +86.299 | 86.299 | 1.28 |
| 2 | 左 | +78.310 | 78.310 | 0.85 |
| 3 | 左 | +56.957 | 56.957 | 0.98 |
| 1 | 右 | -51.050 | 51.050 | 0.67 |
| 2 | 右 | -44.633 | 44.633 | 0.61 |
| 3 | 右 | -53.239 | 53.239 | 0.45 |

集計:

| 指標 | 結果 | 暫定条件 | 判定 |
|---|---:|---:|---|
| 左平均絶対残差 | 73.855 deg | 10 deg以下 | FAIL |
| 右平均絶対残差 | 49.641 deg | 10 deg以下 | FAIL |
| 全体MAE | 61.748 deg | 10 deg以下 | FAIL |
| 最大絶対残差 | 86.299 deg | 15 deg以下 | FAIL |

符号と連続追従は正常だが、角度スケールは現設定`bias=0.23 m`で過大となっている。物理旋回が正確に360度、開始Yawが0度だったと仮定した場合、有効車輪間隔は次式で推定できる。

```text
effective_bias = current_bias * (360 + abs(residual_yaw)) / 360
```

推定値:

| 方向 | 有効車輪間隔平均 |
|---|---:|
| 左 | 0.277185 m |
| 右 | 0.261715 m |
| 左右全体 | 0.269450 m |

旋回中の中心並進は最大約1.3 cmであり、純旋回の並進分離は良好である。一方、左右で推定有効車輪間隔に約1.55 cmの差があり、単一の`bias`だけでは全残差を完全には除けない可能性がある。

ただし、提示結果には各試行のreset直後の開始Yawが含まれていない。開始Yawが0でなければ停止時Yawをそのまま360度残差にできないため、まだ`bias`を書き換えない。開始Yawと終了Yawを同一試行で記録する左右各1回の確認後に、暫定`bias`を決定する。

### 3.21 原点確認付き360度校正（2026年8月18日）

右・左各1回について、reset直後と物理360度旋回後のPoseを同一試行内で記録した。両方向とも開始Poseは完全な原点だった。

```text
position: [0, 0, 0]
orientation: [0, 0, 0, 1]
```

終了Quaternionを`yaw = 2 * atan2(z, w)`でYawへ変換した結果は次のとおりである。

| 方向 | 終了Yaw [deg] | 中心並進 [cm] | 現biasからの有効車輪間隔 [m] |
|---|---:|---:|---:|
| 右360度 | -55.172 | 0.415 | 0.265249 |
| 左360度 | +49.308 | 0.940 | 0.261502 |

開始Yawが0であるため、約50～55度の残差が実際に存在することが確定した。符号は両方向とも回転角の過大評価を示す。現行`bias=0.23 m`は床面を含む実機条件で小さすぎる。

左右1回ずつから求めた校正用平均値:

```text
provisional effective bias = 0.2633755 m
```

左右別推定値の差は約`3.75 mm`で、先の6試行より一致した。中心並進も1 cm未満である。したがって、校正用データとしてこの左右ペアを採用し、暫定値を`0.2634 m`へ丸めて適用する候補とする。

適用後は、校正に用いていない新規の左3回・右3回をholdoutとして測定する。holdout結果を見て同じ値を再調整した場合、その6試行は正式holdoutとして扱わない。

### 3.22 `bias=0.2634 m`の360度holdout（2026年8月18日）

暫定`bias=0.2634 m`を適用して再ビルド・再起動後、校正に使用していない右3回・左3回を測定した。全試行でreset直後のPoseが完全な原点であることを確認した。

終了QuaternionをYawへ変換した結果:

| 試行 | 方向 | 停止時Yaw [deg] | 絶対残差 [deg] | 中心並進 [cm] |
|---:|---|---:|---:|---:|
| 1 | 右 | +3.132 | 3.132 | 0.511 |
| 2 | 右 | +7.622 | 7.622 | 0.546 |
| 3 | 右 | +0.943 | 0.943 | 0.357 |
| 1 | 左 | +4.902 | 4.902 | 0.683 |
| 2 | 左 | +12.193 | 12.193 | 0.979 |
| 3 | 左 | +0.616 | 0.616 | 1.016 |

集計:

| 指標 | 結果 | 合格条件 | 判定 |
|---|---:|---:|---|
| 右MAE | 3.899 deg | 10 deg以下 | PASS |
| 左MAE | 5.904 deg | 10 deg以下 | PASS |
| 全体MAE | 4.901 deg | 10 deg以下 | PASS |
| 最大絶対残差 | 12.193 deg | 15 deg以下 | PASS |
| 最大中心並進 | 1.016 cm | 探索値 | 記録 |

全体平均角度誤差は360度に対して約`1.36%`、最大誤差は約`3.39%`である。左2は操作者から「少し回しすぎた」と申告されたが、事後除外せずholdoutへ含めたまま評価し、それでも最大15度条件を満たした。

現行値`bias=0.2634 m`を採用し、このholdout結果を見て再調整しない。これにより、車輪ODOMは方向、直進距離、旋回角度、TF追従の全確認に合格した。

### 3.23 採用差分とGit分離方針（2026年8月18日）

`kobuki_core`の作業ツリーでは、今回の校正対象だけが変更されている。

```text
M src/driver/diff_drive.cpp
```

差分:

```diff
-  bias(0.23),
+  bias(0.2634),
```

`kobuki_ros`では今回の変更に加え、既存のlaunch変更が存在する。

```text
M  kobuki_node/config/kobuki_node_params.yaml  # 今回の変更
M  kobuki_node/launch/kobuki_node-launch.py    # 既存変更
?? kobuki_node/launch/kobuki_bp_node-launch    # 既存未追跡ファイル
```

今回の設定差分:

```diff
-    use_imu_heading: true
+    use_imu_heading: false
```

ODOM校正の来歴を明確にするため、次の2ファイルだけをそれぞれのリポジトリで明示的にstage・commitする。既存のlaunch 2件はstageせず、内容を変更しない。

```text
kobuki_core/src/driver/diff_drive.cpp
kobuki_ros/kobuki_node/config/kobuki_node_params.yaml
```

### 3.24 採用差分のコミット結果（2026年8月18日）

対象2ファイルは、それぞれ独立したKobukiリポジトリへコミットした。

| リポジトリ | コミット | 内容 |
|---|---|---|
| `kobuki_core` | `a9f053cc` | `Calibrate Kobuki effective wheelbase` |
| `kobuki_ros` | `3f4305a` | `Use wheel odometry when IMU heading is unavailable` |

各コミットは1ファイル、1行だけの変更であり、既存のlaunch変更は含めていない。ただし、コミット時点では両リポジトリとも`detached HEAD`だったため、次作業の前に名前付きブランチを作成してコミットを参照可能な状態にする。

その後、両リポジトリで次のブランチを作成し、`detached HEAD`を解消した。

```text
experiment/2026-08-18-odom-calibration
```

確認結果:

- `kobuki_core`: 作業ツリーはクリーン。
- `kobuki_ros`: 今回対象外の`kobuki_node-launch.py`変更と`kobuki_bp_node-launch`未追跡ファイルだけが残存。
- ODOM校正対象2ファイルに未コミット差分はない。

### 3.25 修正済みODOM録画ドライラン（2026年8月18日）

録画:

```text
/home/hsr/Downloads/recoding/odom_corrected_dryrun_20260818_160424_040
```

`raw.avi`、`bev.avi`、`detection.avi`、`detections.csv`、`metadata.json`が保存されていた。3動画とCSVはすべて990フレームで一致し、`odom_available_rate=1.0`だった。

| 状態 | フレーム数 | 平均linear.x [m/s] | 平均angular.z [rad/s] | 判定 |
|---|---:|---:|---:|---|
| 停止 | 384 | +0.0001 | +0.0001 | PASS |
| 前進 | 132 | +0.0757 | -0.0020 | PASS |
| 右その場旋回 | 174 | +0.0017 | -0.2730 | PASS |
| 左その場旋回 | 272 | -0.0018 | +0.3908 | PASS |

全記録の範囲は`linear.x=-0.0128..+0.0853 m/s`、`angular.z=-0.4048..+0.6314 rad/s`だった。映像上の前進・左右旋回と符号も一致した。したがって、修正済み`/odom`は`bird_eye.py`へ欠損なく記録され、停止・直進・旋回を正しく分離できる。

青箱なしにもかかわらず生の青領域候補は53/990フレームで発生したが、全件が観測ゲートで棄却され、トラック、TTC、`WARNING/CRITICAL`は0件だった。このドライラン範囲では停止時誤発火なしである。

実時間はmonotonic時刻で39.56秒、有効処理速度は約25.0 fpsだった。一方、AVIは固定30 fps・33.0秒として保存されている。動画3本とCSVのフレーム番号対応は維持されるが、AVI単体の再生時間は実時間より約16.6%短い。動的評価ではCSVの`monotonic_time_sec`を正の時刻基準とし、AVI再生時間をTTC基準に使用しない。

集計結果:

```text
Experimental_results/2026-08-18_odom_corrected_dryrun_summary.csv
```

既存集計の`moving_frames`は`abs(odom_linear_mps)>0.03`だけを数えるため、旋回フレームを含まない。この録画の`moving_frames=132`は前進区間のみを意味し、旋回ODOMの欠損ではない。

## 4. 標準実装との差分

標準的なKobuki ODOM実装は、積算位置とyaw Quaternionを`pose`へ、並進速度を`twist.linear.x`へ、角速度を`twist.angular.z`へ格納する。現在の出力はこの挙動と一致しない。

参考:

- [ROS Kobuki odometry.cpp source](https://docs.ros.org/en/kinetic/api/kobuki_node/html/odometry_8cpp_source.html)
- [Kobuki ROS 2 package](https://github.com/CollaborativeRoboticsLab/kobuki)

この差分の原因候補は、使用中ROS 2移植版の不具合、ビルドされた実行ファイルと想定ソースの不一致、またはドライバ内部でのIMU・ODOM更新不成立である。原因はまだ確定していない。

## 5. 次に実施する確認

### 5.1 車輪名と並び順

停止中に次を実行する。

```bash
ros2 topic echo /joint_states --once
```

`name`と`velocity`の対応を記録する。

その後、低速前進中と低速その場回転中に次を実行する。

```bash
ros2 topic echo /joint_states
```

確認項目:

- 前進時の左右車輪の符号
- その場回転時の左右車輪の符号
- 配列順が`wheel_left_joint`, `wheel_right_joint`か
- `velocity`の単位がrad/sとして妥当か

### 5.2 IMU角速度

その場回転中に次を確認する。

```bash
ros2 topic echo /sensors/imu_data --field angular_velocity
```

続けて生値も確認する。

```bash
ros2 topic echo /sensors/imu_data_raw --field angular_velocity
```

左旋回と右旋回で`z`の符号が反転し、停止時にほぼ0へ戻るか確認する。

`/sensors/imu_data`は旋回中も変化しないことを確認済み。次は次の順で、発行周波数、メッセージ全体、生値を確認する。

```bash
ros2 topic hz /sensors/imu_data
```

```bash
ros2 topic echo /sensors/imu_data --once
```

```bash
ros2 topic hz /sensors/imu_data_raw
```

```bash
ros2 topic echo /sensors/imu_data_raw --field angular_velocity
```

`angular_velocity_covariance[0] == -1`の場合は、角速度を提供していないというROSメッセージ上の表明として扱う。生値も変化しない場合は、方針A（IMU＋車輪）を除外し、左右車輪のみを第一候補とする。

### 5.3 車輪速度の符号校正

停止中の配列順は確認できたが、車輪の正方向はまだ確定していない。機体を浮かせず床上で、低速前進中に次を実行する。

```bash
ros2 topic echo /joint_states --field velocity
```

前進時の左・右の符号と代表値を記録する。その後、左旋回と右旋回でも同じ確認を行う。左右車輪から速度を計算する実装は、この符号校正が終わるまで開始しない。

### 5.4 TF

フレーム名を確認する。

```bash
ros2 topic echo /odom --once --field child_frame_id
```

`child_frame_id`が`base_footprint`なら、その場回転中に次を実行する。

```bash
ros2 run tf2_ros tf2_echo odom base_footprint
```

Rotationが変化する場合、`/odom.pose`が固定でもTFからyawを得られる。TFも固定なら車輪またはIMUから再構成する。

確認結果: **不合格**。その場旋回中もYawは0のままで、X並進だけが変化した。TFを代替値として使用せず、左右車輪から再構成する。

### 5.5 使用中実行ファイルの特定

```bash
ros2 pkg executables | grep -i kobuki
```

```bash
ros2 pkg prefix kobuki
```

実際に起動しているパッケージと実行ファイルを特定し、想定ソースと比較する。

ROS 2パッケージ検索では`kobuki_velocity_smoother`しか見つからず、`kobuki`パッケージは見つからなかった。次はOSプロセスから実体を確認する。

```bash
pgrep -af kobuki
```

表示された`/kobuki`ノード本体と考えられるPIDに対して、次を実行する。

```bash
readlink -f /proc/PID/exe
```

```bash
tr '\0' ' ' < /proc/PID/cmdline
```

`PID`は実際の数字へ置き換える。必要に応じて親プロセスも確認する。

```bash
ps -o pid,ppid,user,lstart,args -p PID
```

確認結果: `/home/matunuc/kobuki_ws/install/kobuki_node/lib/kobuki_node/kobuki_ros_node`がノード本体だった。次は次のコマンドでoverlayとソースを確認する。

```bash
bash -lc 'source /opt/ros/humble/setup.bash; source ~/kobuki_ws/install/setup.bash; ros2 pkg prefix kobuki_node; ros2 pkg executables kobuki_node'
```

```bash
find ~/kobuki_ws/src -type f \( -name '*.cpp' -o -name '*.hpp' -o -name '*.h' \) | sort
```

```bash
rg -n 'twist|angular|linear|odometry|joint_states|wheel_left|wheel_right' ~/kobuki_ws/src
```

ソース位置の特定まで完了した。次はODOM計算のデータフローを確認する。

```bash
sed -n '450,540p' /home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_core/src/driver/kobuki.cpp
```

```bash
sed -n '1,210p' /home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_ros/kobuki_node/src/odometry.cpp
```

```bash
sed -n '560,610p' /home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_ros/kobuki_node/src/kobuki_ros.cpp
```

確認対象は、左右エンコーダ差分から並進量と回転量を作る式、`pose_update_rates_`の各要素の意味、更新時間`dt`、IMU heading使用時の分岐である。

確認結果として、IMU heading使用時の分岐がYawと角速度を無効なIMU値で上書きしていることを特定した。次は`diff_drive.update()`の実装を確認する。

```bash
grep -RInE \
  --include='*.cpp' \
  --include='*.hpp' \
  --include='*.h' \
  'pose_update_rates|class.*Diff|DiffDrive|diff_drive' \
  /home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_core
```

検索結果に表示された`diff_drive`の実装ファイルについて、`update()`関数全体を取得する。

検索結果から実装ファイルを特定済み。次を実行する。

```bash
sed -n '1,115p' /home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_core/src/driver/diff_drive.cpp
```

内容確認まで完了した。次は`use_imu_heading`の設定元を特定する。

```bash
grep -RIn 'use_imu_heading' /home/matunuc/kobuki_ws/src /home/matunuc/ffb 2>/dev/null
```

設定ファイルを特定後、`false`で再起動する比較試験を行う。ROSパラメータを実行中に変更するだけでは、コンストラクタで保持された`use_imu_heading_`へ反映されない可能性があるため、設定元を変更してノードを再起動する。

コード確認により、再起動が必要であることを確認した。次は使用中launchのparameter指定を検索する。

```bash
grep -RInE 'kobuki_ros_node|kobuki_node_params|parameters=' /home/matunuc/kobuki_ws/src /home/matunuc/ffb 2>/dev/null
```

検索結果からFFB側launchが実使用経路だと判明した。次はソース側とinstall側を確認する。

```bash
sed -n '1,110p' /home/matunuc/ffb/src/FFB_feedback_control/src/oit/launch/kobuki_vehicle_launch.py
```

```bash
sed -n '1,110p' /home/matunuc/ffb/src/FFB_feedback_control/src/oit/launch/kobuki_launch.py
```

```bash
sed -n '1,110p' /home/matunuc/ffb/install/oit/share/oit/launch/kobuki_vehicle_launch.py
```

確認完了。次は変更前のGit状態とinstall側設定のリンク先を確認し、`kobuki_node`側YAMLだけを`false`へ変更して再ビルド・再起動する。

```bash
git -C /home/matunuc/kobuki_ws/src/turtlebot2_ros2 status --short
```

```bash
readlink -f /home/matunuc/kobuki_ws/install/kobuki_node/share/kobuki_node/config/kobuki_node_params.yaml
```

## 6. 修正方針候補

### 方針A: IMU＋車輪

IMUの`angular_velocity.z`が有効と確認できた場合は、角速度をIMU、並進速度を左右車輪から算出できる。ただし、今回の観測では旋回を明瞭に識別できていないため、現時点では保留とする。

### 方針B: 左右車輪のみ

IMUが無効でも、左右車輪速度が得られれば差動二輪モデルから算出できる。

```text
v_left  = sign_left  × wheel_radius × omega_left
v_right = sign_right × wheel_radius × omega_right

linear  = (v_right + v_left) / 2
angular = (v_right - v_left) / wheel_separation
```

`sign_left`と`sign_right`は前進試験で決定する。Kobukiの公称値は車輪半径約0.035 m、車輪間隔約0.23 mだが、使用中ドライバまたは実機設定を確認してから採用し、推測値をそのまま固定しない。

2026年8月18日の追加試験により、現在観測される符号は次のとおりである。

- 前進: 左正、右正
- その場回転: 左右が逆符号

このため、車輪のみでの復元は実現可能性が高く、現時点の第一候補とする。

### 現時点の採用判断

1. `use_imu_heading=false`を車輪ODOMの修正候補として維持する。
2. keyopによる左旋回、右旋回、前進、後退の符号と運動分離は合格。停止時の静止ノイズを追加確認する。
3. TFのYaw追従と停止時の積算姿勢安定性は合格。必要に応じて停止時`twist`の最大値を補足する。
4. 1 m直進精度は合格し、車輪半径0.035 mを維持する。
5. 左右360度旋回は`bias=0.2634 m`の新規holdoutで全6試行PASS。全体MAE 4.901度、最大12.193度だった。
6. 生IMUは補助記録として残すが、旋回速度の主値には採用しない。
7. 独立車輪ODOMブリッジは実装せず、`use_imu_heading=false`、`bias=0.2634 m`の既存`/odom`を実験へ採用する。
8. Kobukiワークスペースの変更差分とコミットIDを保存し、オフライン回帰と短時間ドライラン後に動的TTC試験へ進む。

### 方針C: コマンド速度

`/cmd_vel`は意図した指令であり、実測速度ではない。表示や一時的な経路予測フォールバックには使えるが、TTC絶対精度の正解値には使用しない。

## 7. 実装時の要件

修正する場合は、元の不正な`/odom`値を上書きして隠さず、CSVへ次を分けて保存する。

- raw odom linear/angular
- wheel-derived linear/angular
- IMU angular
- 実際に採用したlinear/angular
- 採用ソース
- センサー更新時刻と有効状態

静止、前進、後退、左旋回、右旋回、その場回転で符号と大きさを確認した後に、動的TTCと経路判定を再開する。
