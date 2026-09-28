let
  # Pinned to the environment used by the originating strain workflow.
  pkgs = import (fetchTarball
    "https://github.com/NixOS/nixpkgs/archive/fabb8c9deee281e50b1065002c9828f2cf7b2239.tar.gz") {};
  python = pkgs.python3.withPackages (packages: with packages; [
    numpy
    scipy
    matplotlib
  ]);
in pkgs.mkShell {
  packages = [ python ];
  shellHook = ''
    export PATH="$PWD/bin:$PATH"
  '';
}
