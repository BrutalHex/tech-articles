# KIND cluster template (rendered by Makefile with absolute gVisor binary paths).
# gVisor (runsc) is mounted from the host into the control-plane node and registered
# with containerd so RuntimeClass/gvisor (handler: runsc) can schedule sandboxes.
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
containerdConfigPatches:
  - |-
    [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc]
      runtime_type = "io.containerd.runsc.v1"
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 30080
        hostPort: 30080
        protocol: TCP
    extraMounts:
      - hostPath: __BIN_DIR__/runsc
        containerPath: /usr/local/bin/runsc
        readOnly: true
      - hostPath: __BIN_DIR__/containerd-shim-runsc-v1
        containerPath: /usr/local/bin/containerd-shim-runsc-v1
        readOnly: true
    kubeadmConfigPatches:
      - |
        kind: KubeletConfiguration
        evictionHard:
          memory.available: "50Mi"
          nodefs.available: "10%"
        imageGCHighThresholdPercent: 90
        imageGCLowThresholdPercent: 75
        systemReserved:
          cpu: 25m
          memory: 64Mi
        kubeReserved:
          cpu: 25m
          memory: 64Mi
