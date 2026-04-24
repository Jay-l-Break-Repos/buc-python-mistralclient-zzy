FROM ubuntu:20.04

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies including lsb-release
RUN apt-get update && apt-get install -y \
    git \
    sudo \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    curl \
    wget \
    vim \
    net-tools \
    lsb-release \
    software-properties-common \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create stack user (required by DevStack)
RUN useradd -s /bin/bash -d /opt/stack -m stack
RUN echo "stack ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Switch to stack user
USER stack
WORKDIR /opt/stack

# Clone DevStack
RUN git clone https://opendev.org/openstack/devstack.git

# Create local.conf for DevStack with Mistral enabled
RUN cat > /opt/stack/devstack/local.conf << 'EOF'
[[local|localrc]]
# Passwords
ADMIN_PASSWORD=password
DATABASE_PASSWORD=password
RABBIT_PASSWORD=password
SERVICE_PASSWORD=password

# Enable Mistral
enable_plugin mistral https://opendev.org/openstack/mistral
enable_plugin mistral-dashboard https://opendev.org/openstack/mistral-dashboard

# Enable Horizon
enable_service horizon

# Disable some services to speed up
disable_service tempest
disable_service swift
disable_service s-proxy
disable_service s-object
disable_service s-container
disable_service s-account

# Network configuration
HOST_IP=0.0.0.0
SERVICE_HOST=0.0.0.0

# Logging
LOGFILE=/opt/stack/logs/stack.sh.log
VERBOSE=True
LOG_COLOR=True
EOF

# Install vulnerable python-mistralclient version
RUN pip3 install --user "python-mistralclient<4.3.0"

# Create startup script with FORCE=yes
RUN cat > /opt/stack/start.sh << 'EOF'
#!/bin/bash
cd /opt/stack/devstack

# Create logs directory
mkdir -p /opt/stack/logs

# Set environment variables for DevStack
export FORCE=yes
export TERM=xterm

# Run DevStack
./stack.sh

# Keep container running
tail -f /opt/stack/logs/stack.sh.log
EOF

RUN chmod +x /opt/stack/start.sh

EXPOSE 80 443 5000 8774 8989

CMD ["/opt/stack/start.sh"]