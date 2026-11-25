#!/usr/bin/env bash
# Type Omega server installer: installs Forge and downloads the CurseForge mods of this release.
# Needs Java 17+ and curl. Run it once from this folder; run it again after replacing typeomega-installer/ to update mods.
set -euo pipefail
cd "$(dirname "$0")"
source <(sed 's/^/TYPEOMEGA_/' typeomega-installer/versions.txt)

FORGE="${TYPEOMEGA_minecraft}-${TYPEOMEGA_forge}"
FORGE_JAR="typeomega-installer/forge-${FORGE}-installer.jar"
FORGE_SHA256="75cfcb11f60cc641dc83757c1357c08c9bdba255ec529feb115c5e89a59cf75a"
BOOT_JAR="typeomega-installer/packwiz-installer-bootstrap.jar"
BOOT_SHA256="a8fbb24dc604278e97f4688e82d3d91a318b98efc08d5dbfcbcbcab6443d116c"

fetch() { # url file sha256
    if [ ! -f "$2" ] || ! echo "$3  $2" | sha256sum -c --status -; then
        curl -fL --retry 3 -o "$2" "$1"
        echo "$3  $2" | sha256sum -c -
    fi
}

fetch "https://maven.minecraftforge.net/net/minecraftforge/forge/${FORGE}/forge-${FORGE}-installer.jar" "$FORGE_JAR" "$FORGE_SHA256"
fetch "https://github.com/packwiz/packwiz-installer-bootstrap/releases/download/v0.0.3/packwiz-installer-bootstrap.jar" "$BOOT_JAR" "$BOOT_SHA256"

if [ ! -f run.sh ]; then
    java -jar "$FORGE_JAR" --installServer
fi
java -jar "$BOOT_JAR" -g -s server "typeomega-installer/pack/pack.toml"
echo "Done. Accept the EULA (eula.txt) and start the server with ./run.sh"
