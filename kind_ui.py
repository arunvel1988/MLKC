from flask import Flask, render_template, request,jsonify, redirect, session, url_for, Response
import sqlite3
import subprocess
import yaml
import json
import threading
import os
import base64
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException
import requests
import time



app = Flask(__name__)


##############################################################################################
########### loading kubeconfig
##############################################################################################

try:
    # Try to load the kubeconfig
    config.load_kube_config()
    print("Kubeconfig loaded successfully")
except ConfigException as e:
    # Handle the case when the kubeconfig is not found or is invalid
    print(f"Kubeconfig not found or invalid: {str(e)}")
    print("Continuing without kubeconfig...")

##############################################################################################
########### loading kubeconfig -----------------------------------------------------END
##############################################################################################

# Create a SQLite database to store cluster details
def create_database():
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS clusters
                 (name TEXT PRIMARY KEY, k8s_version TEXT, num_nodes INTEGER)''')
    conn.commit()
    conn.close()

# Check if a cluster with the same name already exists
def cluster_exists(name):
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM clusters WHERE name=?", (name,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

# Save cluster details to the database
def save_cluster(name, k8s_version, num_nodes):
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("INSERT INTO clusters VALUES (?, ?, ?)", (name, k8s_version, num_nodes))
    conn.commit()
    conn.close()



def generate_kind_config(name, num_control_plane_nodes, num_worker_nodes=1):
    config = {
        "kind": "Cluster",
        "apiVersion": "kind.x-k8s.io/v1alpha4",
        "nodes": [
            {
                "role": "control-plane",
                "extraMounts": [
                    {
                        "hostPath": "/dev",
                        "containerPath": "/dev"
                    },
                    {
                        "hostPath": "/var/run/docker.sock",
                        "containerPath": "/var/run/docker.sock"
                    }
                ]
            }
        ] * num_control_plane_nodes + [
            {"role": "worker"}
            for _ in range(num_worker_nodes)
        ]
    }
    with open(f"kind-config-{name}.yaml", "w") as file:
        yaml.dump(config, file)


def generate_ha_kind_config(name, num_nodes):
    # For HA cluster, one control plane node and multiple workers
    generate_kind_config(name, 1, num_nodes)

def generate_multi_ha_kind_config(name, num_control_plane_nodes, num_nodes):
    # For multi-master HA cluster, multiple control plane nodes and multiple workers
    generate_kind_config(name, num_control_plane_nodes, num_nodes)




@app.route('/create_cluster', methods=['GET', 'POST'])
def create_cluster():
    if request.method == 'POST':
        name = request.form['name']
        k8s_version = request.form['k8s_version']
        cluster_type = request.form['cluster_type']

        if cluster_exists(name):
            error = f"Cluster with name '{name}' already exists."
            return render_template('create_cluster.html', error=error)

        if cluster_type == 'single':
            num_nodes = int(request.form['num_nodes'])
            generate_kind_config(name, num_nodes)
        elif cluster_type == 'ha':
            num_nodes = int(request.form['num_nodes'])
            generate_ha_kind_config(name, num_nodes)
        elif cluster_type == 'multi_ha':
            num_control_plane_nodes = int(request.form['num_control_plane_nodes'])
            num_nodes = int(request.form['num_nodes'])
            generate_multi_ha_kind_config(name, num_control_plane_nodes, num_nodes)
        else:
            error = "Invalid cluster type selected."
            return render_template('create_cluster.html', error=error)

        # Create the Kind cluster
        try:
            subprocess.run(['kind', 'create', 'cluster', '--name', name,
                            '--image', f'kindest/node:v{k8s_version}',
                            '--config', f'kind-config-{name}.yaml'])
            save_cluster(name, k8s_version, num_nodes)
            return redirect(url_for('cluster_created', name=name))
        except subprocess.CalledProcessError as e:
            error = f"Error creating cluster: {str(e)}"
            return render_template('create_cluster.html', error=error)

    return render_template('create_cluster.html')


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/list_clusters')
def list_clusters():
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("SELECT * FROM clusters")
    db_clusters = c.fetchall()
    conn.close()

    

    try:
        kind_output = subprocess.check_output(['kind', 'get', 'clusters']).decode('utf-8')
        kind_clusters = kind_output.strip().split('\n') if kind_output.strip() else []
    except FileNotFoundError:
        # Handle the case where the 'kind' executable is not found
        print("Error: 'kind' executable not found. Please ensure 'kind' is installed and in your PATH.")
        kind_clusters = []


    return render_template('list_clusters.html', db_clusters=db_clusters, kind_clusters=kind_clusters)


@app.route('/delete_cluster', methods=['POST'])
def delete_cluster():
    name = request.form['name']

    

    try:
        result = subprocess.run(['kind', 'delete', 'cluster', '--name', name], check=True, capture_output=True, text=True)
        print(f"Kind cluster '{name}' deleted successfully.")
        print(f"Output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"Error deleting Kind cluster: {str(e)}")
        print(f"Output: {e.output}")
        # Handle the error appropriately (e.g., show an error message to the user)
        error_message = f"Failed to delete cluster '{name}'. Please check the logs for more information."
        # Redirect or display the error message as needed   
    except FileNotFoundError:
        print("Error: 'kind' executable not found. Please ensure 'kind' is installed and in your PATH.")
        # Handle the FileNotFoundError (e.g., print an error message, exit gracefully, etc.)


    # Delete the cluster from the database
    conn = sqlite3.connect('clusters.db')
    c = conn.cursor()
    c.execute("DELETE FROM clusters WHERE name=?", (name,))
    conn.commit()
    conn.close()

    success_message = f"Cluster '{name}' deleted successfully."
    return redirect(url_for('list_clusters', message=success_message))



@app.route('/cluster_info/<name>')
def cluster_info(name):
    # Get cluster information using kubectl
    try:
        # Change the Kubernetes context to the selected cluster
        context_name = f"kind-{name}"
        subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)

        # Get namespaces
        namespaces_output = subprocess.check_output(['kubectl', 'get', 'namespaces', '-o', 'json']).decode('utf-8')
        namespaces = json.loads(namespaces_output)['items']
        namespaces_data = [namespace['metadata']['name'] for namespace in namespaces]

        # Get nodes
        nodes_output = subprocess.check_output(['kubectl', 'get', 'nodes', '-o', 'json']).decode('utf-8')
        nodes = json.loads(nodes_output)['items']
        nodes_data = []
        
        for node in nodes:
            labels = node['metadata']['labels']
            roles = []

            # Check for control plane role label
            if 'node-role.kubernetes.io/control-plane' in labels:
                roles.append('control-plane')

            # Check for worker role label
            if 'node-role.kubernetes.io/worker' in labels:
                roles.append('worker')

            # If no specific role label found, assign 'unknown' role
            if not roles:
                roles.append('unknown')

            nodes_data.append({
                'name': node['metadata']['name'],
                'status': node['status']['conditions'][-1]['type'],
                'roles': ','.join(roles),
                'age': node['metadata']['creationTimestamp'],
                'version': node['status']['nodeInfo']['kubeletVersion']
            })

        return render_template('cluster_info.html', name=name, namespaces=namespaces_data, nodes=nodes_data)

    except subprocess.CalledProcessError as e:
        error = f"Error getting cluster information: {str(e)}"
        return render_template('cluster_info.html', name=name, error=error)

@app.route('/namespace_data', methods=['POST'])
def namespace_data():
    cluster_name = request.form.get('cluster_name')
    namespace = request.form.get('namespace')

    # Change the Kubernetes context to the selected cluster
    context_name = f"kind-{cluster_name}"
    subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)

    # Get deployments for the specified namespace
    deployments_output = subprocess.check_output(['kubectl', 'get', 'deployments', '-n', namespace, '-o', 'json']).decode('utf-8')
    deployments = json.loads(deployments_output)['items']
    deployments_data = []
    for deployment in deployments:
        deployments_data.append({
            'name': deployment['metadata']['name'],
            'ready': f"{deployment['status'].get('readyReplicas', 'N/A')}/{deployment['spec']['replicas']}",
            'uptodate': deployment['status'].get('updatedReplicas', 'N/A'),
            'available': deployment['status'].get('availableReplicas', 'N/A'),
            'age': deployment['metadata']['creationTimestamp']
        })

    # Get pods for the specified namespace
    pods_output = subprocess.check_output(['kubectl', 'get', 'pods', '-n', namespace, '-o', 'json']).decode('utf-8')
    pods = json.loads(pods_output)['items']
    pods_data = []
    for pod in pods:
        pods_data.append({
            'name': pod['metadata']['name'],
            'ready': f"{sum(container['ready'] for container in pod['status']['containerStatuses'])}/{len(pod['spec']['containers'])}",
            'status': pod['status']['phase'],
            'restarts': sum(container['restartCount'] for container in pod['status']['containerStatuses']),
            'age': pod['metadata']['creationTimestamp']
        })

    # Get services for the specified namespace
    services_output = subprocess.check_output(['kubectl', 'get', 'services', '-n', namespace, '-o', 'json']).decode('utf-8')
    services = json.loads(services_output)['items']
    services_data = []
    for service in services:
        services_data.append({
            'name': service['metadata']['name'],
            'type': service['spec']['type'],
            'clusterip': service['spec']['clusterIP'],
            'externalip': ','.join(service['spec'].get('externalIPs', [])),
            'ports': ','.join(f"{port['port']}/{port['protocol']}" for port in service['spec']['ports']),
            'age': service['metadata']['creationTimestamp']
        })

    # Render the data as HTML tables
    deployments_html = render_template('deployments_table.html', deployments=deployments_data)
    pods_html = render_template('pods_table.html', pods=pods_data)
    services_html = render_template('services_table.html', services=services_data)

    return jsonify({
        'deployments': deployments_html,
        'pods': pods_html,
        'services': services_html
    })




@app.route('/get_grafana_password', methods=['GET'])
def get_grafana_secret():
    try:
        # Run the kubectl command to get the Grafana secret
        result = subprocess.run(['kubectl', 'get', 'secret', '--namespace', 'monitoring', 'my-grafana', '-o', 'json'],
                                capture_output=True, check=True, text=True)
        secret_json = json.loads(result.stdout)
        encoded_password = secret_json['data']['admin-password']
        # Decode the base64-encoded password
        decoded_password = base64.b64decode(encoded_password).decode('utf-8')
        return jsonify({'success': True, 'password': decoded_password})
    except subprocess.CalledProcessError as e:
        error_message = f"Error retrieving Grafana secret: {str(e)}"
        return jsonify({'success': False, 'error': error_message})







@app.route('/upload_yaml/<cluster_name>', methods=['GET', 'POST'])
def upload_yaml(cluster_name):
    if request.method == 'POST':
        if 'yaml_file' not in request.files:
            return redirect(url_for('cluster_info', name=cluster_name, error='No file uploaded'))

        file = request.files['yaml_file']

        if file.filename == '':
            return redirect(url_for('cluster_info', name=cluster_name, error='No file selected'))

        yaml_content = file.read().decode('utf-8')

        try:
            context_name = f"kind-{cluster_name}"
            subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
            subprocess.run(['kubectl', 'apply', '-f', '-'], input=yaml_content.encode(), check=True)
            return redirect(url_for('cluster_info', name=cluster_name, message='Deployment successful'))
        except subprocess.CalledProcessError as e:
            error = f"Error deploying YAML: {str(e)}"
            return redirect(url_for('cluster_info', name=cluster_name, error=error))

    return render_template('upload_yaml.html', cluster_name=cluster_name)





def get_namespaces():
    try:
        result = subprocess.run(['kubectl', 'get', 'namespaces', '-o', 'json'], capture_output=True, check=True, text=True)
        namespaces_json = json.loads(result.stdout)
        namespaces = [item['metadata']['name'] for item in namespaces_json['items']]
        return namespaces
    except subprocess.CalledProcessError as e:
        print(f"Error retrieving namespaces: {str(e)}")
        return []






def port_forward_thread(namespace, service_name, host_port, container_port):
    try:
        subprocess.run(['kubectl', 'port-forward', f'svc/{service_name}', '--address', '0.0.0.0', f'{host_port}:{container_port}', '-n', namespace], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error during port forwarding: {str(e)}")

def get_instance_ip():
    try:
        instance_id = requests.get('http://169.254.169.254/latest/meta-data/instance-id').text
        ip_address = subprocess.check_output(['aws', 'ec2', 'describe-instances', '--instance-ids', instance_id, '--query', 'Reservations[*].Instances[*].PublicIpAddress', '--output', 'text'])
        return ip_address.decode().strip()
    except Exception as e:
        print(f"Error getting instance IP: {str(e)}")
        return 'localhost'

@app.route('/port_forward/<cluster_name>', methods=['GET', 'POST'])
def port_forward(cluster_name):
    if request.method == 'POST':
        namespace = request.form['namespace']
        service_name = request.form['service_name']
        container_port = request.form['container_port']
        host_port = request.form['host_port']
        try:
            context_name = f"kind-{cluster_name}"
            subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
            threading.Thread(target=port_forward_thread, args=(namespace, service_name, host_port, container_port)).start()
            instance_ip = get_instance_ip()
            if instance_ip == 'localhost':
                message = f'http://localhost:{host_port}'
            else:
                message = f'http://{instance_ip}:{host_port}'
            return render_template('port_forward.html', cluster_name=cluster_name, message=message, namespaces=get_namespaces(), selected_namespace=namespace, services=get_services(namespace))
        except subprocess.CalledProcessError as e:
            error = f"Error during port forwarding: {str(e)}"
            return redirect(url_for('cluster_info', name=cluster_name, error=error))
    return render_template('port_forward.html', cluster_name=cluster_name, namespaces=get_namespaces(), selected_namespace=None, services=[])


@app.route('/cluster_created')
def cluster_created():
    name = request.args.get('name')
    return render_template('cluster_created.html', name=name)


@app.route('/check_preq')
def check_preq():
    # Check if Docker is installed
    try:
        docker_output = subprocess.check_output(['docker', '--version']).decode('utf-8').strip()
        docker_installed = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        docker_installed = False
        docker_output = 'Docker is not installed'

    # Check if kubectl is installed
    try:
        kubectl_output = subprocess.check_output(['kubectl', 'version', '--client']).decode('utf-8').strip()
        kubectl_installed = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        kubectl_installed = False
        kubectl_output = 'kubectl is not installed'

    # Check if Kind is installed
    try:
        kind_output = subprocess.check_output(['kind', 'version']).decode('utf-8').strip()
        kind_installed = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        kind_installed = False
        kind_output = 'Kind is not installed'

    # Check if Helm is installed
    try:
        helm_output = subprocess.check_output(['helm', 'version']).decode('utf-8').strip()
        helm_installed = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        helm_installed = False
        helm_output = 'Helm is not installed'

    # Check if Python3 is installed
    try:
        python3_output = subprocess.check_output(['python3', '--version']).decode('utf-8').strip()
        python3_installed = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        python3_installed = False
        python3_output = 'Python3 is not installed'

    return render_template('check_preq.html',
                           docker_installed=docker_installed, docker_output=docker_output,
                           kubectl_installed=kubectl_installed, kubectl_output=kubectl_output,
                           kind_installed=kind_installed, kind_output=kind_output,
                           helm_installed=helm_installed, helm_output=helm_output,
                           python3_installed=python3_installed, python3_output=python3_output)


@app.route('/install_tool', methods=['POST'])
def install_tool():
    tool = request.form['tool']

    if tool == 'docker':
        subprocess.run(['chmod', '+x', './scripts/install_docker.sh'])
        subprocess.run(['./scripts/install_docker.sh'])  # Modify the path as necessary
    elif tool == 'kubectl':
        subprocess.run(['chmod', '+x', './scripts/install_kubectl.sh'])
        subprocess.run(['./scripts/install_kubectl.sh'])
    elif tool == 'kind':
        subprocess.run(['chmod', '+x', './scripts/install_kind.sh'])
        subprocess.run(['./scripts/install_kind.sh'])  # Modify the path as necessary
    elif tool == 'helm':
        subprocess.run(['chmod', '+x', './scripts/install_helm.sh'])
        subprocess.run(['./scripts/install_helm.sh'])  # Modify the path as necessary
    elif tool == 'python3':
        subprocess.run(['chmod', '+x', './scripts/install_python.sh'])
        subprocess.run(['./scripts/install_python3.sh'])  # Modify the path as necessary

    return redirect(url_for('check_preq'))


@app.route('/deploy_helm/<cluster_name>', methods=['GET', 'POST'])
def deploy_helm(cluster_name):
    if request.method == 'POST':
        deployment_method = request.form.get('deployment_method')
        if deployment_method == 'repository':
            repo_name = request.form.get('repo_name')
            chart_repo = request.form.get('chart_repo')
            chart_name = request.form.get('chart_name')
            chart_version = request.form.get('chart_version')
            release_name = request.form.get('release_name')
            try:
                context_name = f"kind-{cluster_name}"
                subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
                # Add the Helm chart repository
                subprocess.run(['helm', 'repo', 'add', repo_name, chart_repo], check=True)
                subprocess.run(['helm', 'repo', 'update'], check=True)
                # Install the Helm chart from the repository
                subprocess.run(['helm', 'install', release_name, f'{repo_name}/{chart_name}', '--version', chart_version], check=True)
                return jsonify({'success': True, 'message': 'Helm chart deployed successfully'})
            except subprocess.CalledProcessError as e:
                error = f"Error deploying Helm chart: {str(e)}"
                return jsonify({'success': False, 'error': error})
        elif deployment_method == 'tgz':
            if 'chart_file' not in request.files:
                return jsonify({'success': False, 'error': 'No file uploaded'})
            file = request.files['chart_file']
            if file.filename == '':
                return jsonify({'success': False, 'error': 'No file selected'})
            release_name_tgz = request.form.get('release_name_tgz')
            # Save the uploaded packaged Helm chart file to cwd
            chart_filename = file.filename  # Use the original filename
            chart_path = os.path.join(os.getcwd(), chart_filename)
            file.save(chart_path)
            try:
                context_name = f"kind-{cluster_name}"
                subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
                # Install the uploaded packaged Helm chart
                subprocess.run(['helm', 'install', release_name_tgz, chart_path], check=True)
                return jsonify({'success': True, 'message': 'Helm chart deployed successfully'})
            except subprocess.CalledProcessError as e:
                error = f"Error deploying Helm chart: {str(e)}"
                return jsonify({'success': False, 'error': error})
    # If the request method is not POST or there's no 'deployment_method' specified
    return render_template('deploy_helm.html', cluster_name=cluster_name)

@app.route('/helm_releases')
def helm_releases():
    try:
        # Execute the 'helm ls' command and capture the output
        output = subprocess.check_output(['helm', 'ls', '-o', 'json'])
        
        # Parse the JSON output
        releases = json.loads(output)
        
        # Extract the relevant details from each release
        release_data = []
        for release in releases:
            release_info = {
                'name': release['name'],
                'namespace': release['namespace'],
                'revision': release['revision'],
                'status': release['status'],
                'chart': release['chart'],
                'app_version': release['app_version']
            }
            release_data.append(release_info)
        
        return jsonify(release_data)
    
    except subprocess.CalledProcessError as e:
        error = f"Error fetching Helm releases: {str(e)}"
        return jsonify({'error': error}), 500


@app.route('/delete_helm_release/<release_name>', methods=['DELETE'])
def delete_helm_release(release_name):
    try:
        # Execute the 'helm uninstall' command to delete the release
        subprocess.run(['helm', 'uninstall', release_name], check=True)
        
        return jsonify({'success': True})
    
    except subprocess.CalledProcessError as e:
        error = f"Error deleting Helm release: {str(e)}"
        return jsonify({'success': False, 'error': error}), 500






@app.route('/devops_tools/<cluster_name>', methods=['GET', 'POST', 'DELETE'])
def devops_tools(cluster_name):
    if request.method == 'POST':
        selected_tool = request.form.get('tool')
        try:
            context_name = f"kind-{cluster_name}"
            subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
            if selected_tool == 'ci':
                # Install Tekton for CI
                if is_tekton_installed():
                    return jsonify({'success': True, 'message': 'Tekton is already installed'})
                subprocess.run(['chmod', '+x', './scripts/install_tekton.sh'], check=True)
                process = subprocess.Popen(['./scripts/install_tekton.sh'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = process.communicate()
                if process.returncode != 0:
                    error = f"Error executing install_tekton.sh script. Return code: {process.returncode}\n"
                    error += f"stdout: {stdout.decode('utf-8')}\n"
                    error += f"stderr: {stderr.decode('utf-8')}"
                    print(error)  # Print the error for logging purposes
                    return jsonify({'success': False, 'error': error})
                return jsonify({'success': True, 'message': 'Tekton installed successfully'})
            elif selected_tool == 'cd':
                # Install ArgoCD for CD
                if is_argocd_installed():
                    return jsonify({'success': True, 'message': 'Argocd is already installed'})
                subprocess.run(['kubectl', 'create', 'namespace', 'argocd'], check=True)
                subprocess.run(['kubectl', 'apply', '-n', 'argocd', '-f', 'https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml'], check=True)
                return jsonify({'success': True, 'message': 'ArgoCD installed successfully'})
            
            elif selected_tool == 'buildpacks':
                # Install ArgoCD for CD
                if is_buildpacks_installed():
                    return jsonify({'success': True, 'message': 'buildpacks is already installed'})
                
                

                url = "https://github.com/buildpacks/pack/releases/download/v0.33.2/pack-v0.33.2-linux.tgz"
                curl_command = f"curl -sSL '{url}'"
                tar_command = "sudo tar -C /usr/local/bin/ --no-same-owner -xzv pack"

                curl_process = subprocess.Popen(curl_command, stdout=subprocess.PIPE, shell=True)
                tar_process = subprocess.Popen(tar_command, stdin=curl_process.stdout, shell=True)

                curl_process.stdout.close()
                exit_code = tar_process.wait()

                if exit_code != 0:
                    print("Error occurred during the installation process.")
                    return jsonify({'success': True, 'message': 'Not installed installed successfully'})
                else:
                    print("Pack buildpack installed successfully.")
                    return jsonify({'success': True, 'message': 'installed successfully'})




            elif selected_tool == 'crossplane':
                # Install Crossplane
                if is_crossplane_installed():
                    return jsonify({'success': True, 'message': 'Crossplane is already installed'})
                subprocess.run(['kubectl', 'create', 'namespace', 'crossplane-system'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'crossplane-stable', 'https://charts.crossplane.io/stable'], check=True)
                
                subprocess.run(['helm', 'repo', 'update'], check=True)
                subprocess.run(['helm', 'install', 'crossplane', 'crossplane-stable/crossplane', '--namespace', 'crossplane-system'], check=True)
                
                return jsonify({'success': True, 'message': 'crossplane installed successfully'})
            

            elif selected_tool == 'airflow':
                # Install Airflow
                if is_airflow_installed():
                    return jsonify({'success': True, 'message': 'Airflow is already installed'})
                subprocess.run(['kubectl', 'create', 'namespace', 'airflow'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'apache-airflow', 'https://airflow.apache.org'], check=True)
                
                subprocess.run(['helm', 'repo', 'update'], check=True)
                subprocess.run(['helm', 'install', 'my-airflow', 'apache-airflow/airflow', '--namespace', 'airflow'], check=True)
                
                return jsonify({'success': True, 'message': 'airflow installed successfully'})
            
            elif selected_tool == 'kafka':
    # Install Kafka using Strimzi Kafka Operator

                if is_kafka_installed():
                    return jsonify({'success': True, 'message': 'Kafka is already installed'})

    # Add Strimzi Helm repository
                subprocess.run(['kubectl', 'create', 'namespace', 'strimzi'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'strimzi', 'https://strimzi.io/charts'], check=True)

    # Install Strimzi Kafka Operator
                subprocess.run([
                    'helm', 'install', 'strimzi-kafka-operator', 'strimzi/strimzi-kafka-operator',
                    '--version', '0.38.0',
                    '-n', 'strimzi',
                
                    '-f', './tools/kafka/strimzi-values.yaml'
                ], check=True)

    # Apply Kafka Cluster YAML
                subprocess.run(['kubectl', 'apply', '-f', './tools/kafka/kafka-cluster.yaml'], check=True)

    # Wait for the Kafka Cluster to be ready
                subprocess.run(['kubectl', 'wait', '--for=condition=Ready', '--timeout=300s', '-n', 'strimzi', 'kafka/my-cluster'], check=True)

    # You can add additional steps if needed, such as creating a service, configuring networking, etc.

                return jsonify({'success': True, 'message': 'Kafka installed successfully'})

            elif selected_tool == 'monitoring':
                if is_monitoring_installed():
                    return jsonify({'success': True, 'message': 'Monitoring is already installed'})
                # Install Prometheus and Grafana for monitoring
                subprocess.run(['kubectl', 'create', 'namespace', 'monitoring'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'prometheus-community', 'https://prometheus-community.github.io/helm-charts'], check=True)
                
                subprocess.run(['helm', 'repo', 'update'], check=True)
                subprocess.run(['helm', 'install', 'prometheus', 'prometheus-community/kube-prometheus-stack', '--namespace', 'monitoring'], check=True)

                
               
                return jsonify({'success': True, 'message': 'Prometheus and Grafana installed successfully'})
            
            elif selected_tool == 'vault':
                if is_vault_installed():
                    return jsonify({'success': True, 'message': 'Vault is already installed'})
                # Install Vault
                subprocess.run(['kubectl', 'create', 'namespace', 'vault'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'hashicorp', 'https://helm.releases.hashicorp.com'], check=True)
                
                subprocess.run(['helm', 'repo', 'update'], check=True)
                subprocess.run(['helm', 'install', 'vault', 'hashicorp/vault','-n','vault'], check=True)

                
                
                return jsonify({'success': True, 'message': 'Vault installed successfully'})
            
            elif selected_tool == 'jaeger':
                if is_jaeger_installed():
                    return jsonify({'success': True, 'message': 'Jaeger is already installed'})
                
                try:
                    subprocess.run(['kubectl', 'apply', '-f', 'https://github.com/cert-manager/cert-manager/releases/download/v1.9.0/cert-manager.yaml'], check=True)
                    import time
                    time.sleep(30)
                except subprocess.CalledProcessError as e:
                    return jsonify({'success': False, 'message': f'Error installing cert-manager: {str(e)}'}), 500

    # Check cert-manager pods

                import time
                time.sleep(30)

                try:
                    subprocess.run(['kubectl', 'get', 'pods', '-n', 'cert-manager'], check=True)
                except subprocess.CalledProcessError as e:
                    return jsonify({'success': False, 'message': f'Error checking cert-manager pods: {str(e)}'}), 500




                # Install Vault
                subprocess.run(['kubectl', 'create', 'namespace', 'observability'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'jaegertracing', 'https://jaegertracing.github.io/helm-charts'], check=True)
                
                subprocess.run(['helm', 'repo', 'update'], check=True)
                subprocess.run(['helm', 'install', 'my-release', 'jaegertracing/jaeger-operator','-n','observability'], check=True)
                import time
                time.sleep(30)


                
                try:
                    subprocess.run(['kubectl', 'get', 'deployment', 'my-release-jaeger-operator', '-n', 'observability'], check=True)
                except subprocess.CalledProcessError as e:
                    return jsonify({'success': False, 'message': f'Error checking Jaeger operator deployment: {str(e)}'}), 500


                import time
                time.sleep(25)

 
                jaeger_instance_yaml = '''
            apiVersion: jaegertracing.io/v1
            kind: Jaeger
            metadata:
                name: simplest
                namespace: observability
                '''
                try:
                    subprocess.run(['kubectl', 'apply', '-f', '-'], input=jaeger_instance_yaml.encode(), check=True)
                except subprocess.CalledProcessError as e:
                    return jsonify({'success': False, 'message': f'Error creating Jaeger instance: {str(e)}'}), 500

    
                
                return jsonify({'success': True, 'message': 'Jaeger installed successfully'})
            

            elif selected_tool == 'istio':
                # Install Istio Service Mesh
                if is_istio_installed():
                    return jsonify({'success': True, 'message': 'Istio is already installed'})
                subprocess.run(['kubectl', 'create', 'namespace', 'istio-system'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'istio', 'https://istio-release.storage.googleapis.com/charts'], check=True)                
                subprocess.run(['helm', 'repo', 'update'], check=True)             

                subprocess.run(['helm', 'install', 'istio-base', 'istio/base', '-n', 'istio-system', '--set', 'defaultRevision=default'], check=True)
              
                

                subprocess.run(['helm', 'install', 'istiod', 'istio/istiod', '--namespace', 'istio-system', '--wait'], check=True)
                subprocess.run(['kubectl', 'create', 'namespace', 'istio-ingress'], check=True)

                subprocess.run(['helm', 'install','istio-ingressgateway', 'istio/gateway', '--namespace', 'istio-ingress'], check=True)
                return jsonify({'success': True, 'message': 'Istio installed successfully'})
            else:
                return jsonify({'success': False, 'error': 'Invalid tool selected'})

            
            
            
        except subprocess.CalledProcessError as e:
            error = f"Error installing tool: {str(e)}"
            print(error)  # Print the error for logging purposes
            return jsonify({'success': False, 'error': error})

    elif request.method == 'DELETE':
        selected_tool = request.form.get('tool')
        try:
            context_name = f"kind-{cluster_name}"
            subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
            if selected_tool == 'ci':
                # Delete Tekton for CI
                if not is_tekton_installed():
                    return jsonify({'success': True, 'message': 'Tekton is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'tekton-pipelines', 'tekton-pipelines-resolvers'], check=True)

                return jsonify({'success': True, 'message': 'Tekton deleted successfully'})
            elif selected_tool == 'cd':
                # Delete ArgoCD for CD
                if not is_argocd_installed():
                    return jsonify({'success': True, 'message': 'ArgoCD is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'argocd'], check=True)
                return jsonify({'success': True, 'message': 'ArgoCD deleted successfully'})
            


            elif selected_tool == 'airflow':
                # Delete Airflow
                if not is_airflow_installed():
                    return jsonify({'success': True, 'message': 'airflow is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'airflow'], check=True)
                return jsonify({'success': True, 'message': 'Apache Airflow deleted successfully'})
            

            elif selected_tool == 'jaeger':
                # Delete jaeger
                if not is_jaeger_installed():
                    return jsonify({'success': True, 'message': 'Jaeger is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'observability'], check=True)
                return jsonify({'success': True, 'message': 'Jaeger deleted successfully'})
            

            elif selected_tool == 'crossplane':
                # Delete ArgoCD for CD
                if not is_crossplane_installed():
                    return jsonify({'success': True, 'message': 'crossplane is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'crossplane-system'], check=True)
                return jsonify({'success': True, 'message': 'crossplane deleted successfully'})

            elif selected_tool == 'kafka':
                # Delete ArgoCD for CD
                if not is_kafka_installed():
                    return jsonify({'success': True, 'message': 'Kafka is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'strimzi'], check=True)
                return jsonify({'success': True, 'message': 'ArgoCD deleted successfully'})
            
            elif selected_tool == 'vault':
                # Delete ArgoCD for CD
                if not is_vault_installed():
                    return jsonify({'success': True, 'message': 'Vault is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'vault'], check=True)
                return jsonify({'success': True, 'message': 'Vault deleted successfully'})
            
            elif selected_tool == 'buildpacks':
                # Delete ArgoCD for CD
                if not is_buildpacks_installed():
                    return jsonify({'success': True, 'message': 'is not installed'})
                
                

# Command to list files containing "pack" in /usr/local/bin/
                list_command = "ls /usr/local/bin/ | grep pack"
                list_process = subprocess.run(list_command, shell=True, capture_output=True, text=True)

                if list_process.returncode == 0:
                    files_found = list_process.stdout.strip()
                    print(f"Files found: {files_found}")
                else:
                    print("No files found containing 'pack'.")

# Command to remove the 'pack' binary
                remove_command = "sudo rm /usr/local/bin/pack"
                remove_process = subprocess.run(remove_command, shell=True, capture_output=True, text=True)

                if remove_process.returncode == 0:
                    return jsonify({'success': True, 'message': 'deleted successfully'})
                    
                else:
                    print(f"Error removing the 'pack' binary: {remove_process.stderr}")
                
                


            elif selected_tool == 'monitoring':
                # Delete ArgoCD for CD
                if not is_monitoring_installed():
                    return jsonify({'success': True, 'message': 'Monitoring is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'monitoring'], check=True)
                return jsonify({'success': True, 'message': 'Monitoring deleted successfully'})
            
            elif selected_tool == 'istio':
                # Delete Istio
                if not is_istio_installed():
                    return jsonify({'success': True, 'message': 'Istio is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'istio-system'], check=True)
                subprocess.run(['kubectl', 'delete', 'ns', 'istio-ingress'], check=True)
                return jsonify({'success': True, 'message': 'Istio deleted successfully'})

            else:
                return jsonify({'success': False, 'error': 'Invalid tool selected'})
            

        except subprocess.CalledProcessError as e:
            error = f"Error deleting tool: {str(e)}"
            print(error)  # Print the error for logging purposes
            return jsonify({'success': False, 'error': error})

    else:
        return render_template('devops_tools.html', cluster_name=cluster_name)

def is_tekton_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'tekton-pipelines', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0  # Return True if there are any pods, False otherwise
    except subprocess.CalledProcessError:
        return False  # Return False if there was an error executing the command
    



def is_buildpacks_installed():
    try:
        # Run the 'pack' command and capture its exit code
        subprocess.run(['pack'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        # If the command ran successfully, 'pack' is installed
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        # If the command failed or the 'pack' binary was not found, return False
        return False



def is_airflow_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'airflow', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0  # Return True if there are any pods, False otherwise
    except subprocess.CalledProcessError:
        return False  # Return False if there was an error executing the command


def is_jaeger_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'observability', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0  # Return True if there are any pods, False otherwise
    except subprocess.CalledProcessError:
        return False  # Return False if there was an error executing the command


def is_crossplane_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'crossplane-system', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0  # Return True if there are any pods, False otherwise
    except subprocess.CalledProcessError:
        return False  # Return False if there was an error executing the command

def is_istio_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'istio-system', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0  # Return True if there are any pods, False otherwise
    except subprocess.CalledProcessError:
        return False  # Return False if there was an error executing the command
    
def is_vault_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'vault', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0  # Return True if there are any pods, False otherwise
    except subprocess.CalledProcessError:
        return False  # Return False if there was an error executing the command


def is_kafka_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'kafka', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0  # Return True if there are any pods, False otherwise
    except subprocess.CalledProcessError:
        return False  # Return False if there was an error executing the command


def is_argocd_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'argocd', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0  # Return True if there are any pods, False otherwise
    except subprocess.CalledProcessError:
        return False  # Return False if there was an error executing the command


def is_monitoring_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'monitoring', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0  # Return True if there are any pods, False otherwise
    except subprocess.CalledProcessError:
        return False  # Return False if there was an error executing the command



#################################################################################################
#        security 
###################################################################################################


@app.route('/security_tools/<cluster_name>', methods=['GET', 'POST', 'DELETE'])
def security_tools(cluster_name):
    if request.method == 'POST':
        selected_tool = request.form.get('tool')
        try:
            context_name = f"kind-{cluster_name}"
            subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
            if selected_tool == 'kyverno':
                # Install Kyverno
                if is_kyverno_installed():
                    return jsonify({'success': True, 'message': 'Kyverno is already installed'})
                subprocess.run(['kubectl', 'create', 'namespace', 'kyverno'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'kyverno', 'https://kyverno.github.io/kyverno/'], check=True)
                subprocess.run(['helm', 'repo', 'update'], check=True)
                
                subprocess.run(['helm', 'install', 'kyverno', 'kyverno/kyverno', '-n','kyverno'], check=True)
                return jsonify({'success': True, 'message': 'Kyverno installed successfully'})
            

            elif selected_tool == 'trivy':
                if is_trivy_installed():
                    return jsonify({'success': True, 'message': 'Trivy is already installed'})
                # Install Vault
                subprocess.run(['kubectl', 'create', 'namespace', 'trivy-system'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'aqua', 'https://aquasecurity.github.io/helm-charts/'], check=True)
                
                subprocess.run(['helm', 'repo', 'update'], check=True)
                subprocess.run(['helm', 'install', 'trivy-operator', 'aqua/trivy-operator','-n','trivy-system','--set','trivy.ignoreUnfixed=true'], check=True)

                
                
                return jsonify({'success': True, 'message': 'Trivy installed successfully'})
            

            elif selected_tool == 'chaos':
                if is_chaos_installed():
                    return jsonify({'success': True, 'message': 'chaos is already installed'})
            
                subprocess.run(['kubectl', 'create', 'namespace', 'chaos-mesh'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'chaos-mesh', 'https://charts.chaos-mesh.org'], check=True)
                
                subprocess.run(['helm', 'repo', 'update'], check=True)
                subprocess.run(['helm', 'install', 'chaos-mesh', 'chaos-mesh/chaos-mesh','-n','chaos-mesh'], check=True)
                return jsonify({'success': True, 'message': 'ChaosMesh installed successfully'})
                
                



            elif selected_tool == 'falco':
                # Install Falco
                if is_falco_installed():
                    return jsonify({'success': True, 'message': 'Falco is already installed'})
                subprocess.run(['kubectl', 'create', 'namespace', 'falco'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'falcosecurity', 'https://falcosecurity.github.io/charts'], check=True)
                subprocess.run(['helm', 'repo', 'update'], check=True)
                webhook_url_base64 = "aHR0cHM6Ly9ob29rcy5zbGFjay5jb20vc2VydmljZXMvVDA0QUhTRktMTTgvQjA1SzA3NkgyNlMvV2ZHRGQ5MFFDcENwNnFzNmFKNkV0dEg4"
                webhook_url = base64.b64decode(webhook_url_base64).decode('utf-8')
                command = [
                    'helm', 'install', 'falco', '-n', 'falco',
                    '--set', 'driver.kind=ebpf',
                    '--set', 'tty=true',
                    'falcosecurity/falco',
                    '--set', 'falcosidekick.enabled=true',
                    f'--set', f'falcosidekick.config.slack.webhookurl={webhook_url}',
                    '--set', 'falcosidekick.config.slack.minimumpriority=notice',
                    '--set', 'falcosidekick.config.customfields="user:arunvel"'
                ]
                subprocess.run(command, check=True)
                return jsonify({'success': True, 'message': 'Falco installed successfully'})
            else:
                return jsonify({'success': False, 'error': 'Invalid tool selected'})
        except subprocess.CalledProcessError as e:
            return jsonify({'success': False, 'message': f'Error: {str(e)}'})
    elif request.method == 'DELETE':
        selected_tool = request.form.get('tool')
        try:
            context_name = f"kind-{cluster_name}"
            subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
            if selected_tool == 'kyverno':
                if not is_kyverno_installed():
                    return jsonify({'success': True, 'message': 'Kyverno is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'kyverno'], check=True)
                return jsonify({'success': True, 'message': 'Kyverno deleted successfully'})

            elif selected_tool == 'trivy':
                if not is_trivy_installed():
                    return jsonify({'success': True, 'message': 'trivy is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'trivy-system'], check=True)
                return jsonify({'success': True, 'message': 'Trivy deleted successfully'})


            elif selected_tool == 'chaos':
                if not is_chaos_installed():
                    return jsonify({'success': True, 'message': 'Chaos Mesh is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'chaos-mesh'], check=True)
                return jsonify({'success': True, 'message': 'Chaos Mesh deleted successfully'})
                    
                
                    
            
            elif selected_tool == 'falco':
                if not is_falco_installed():
                    return jsonify({'success': True, 'message': 'Falco is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'falco'], check=True)
                return jsonify({'success': True, 'message': 'Falco deleted successfully'})
            else:
                return jsonify({'success': False, 'error': 'Invalid tool selected'})
        except subprocess.CalledProcessError as e:
            return jsonify({'success': False, 'message': f'Error: {str(e)}'})
    else:
        return render_template('security_tools.html', cluster_name=cluster_name)




def is_trivy_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'trivy-system', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0
    except subprocess.CalledProcessError:
        return False

def is_chaos_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'chaos-mesh', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0
    except subprocess.CalledProcessError:
        return False

def is_kyverno_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'kyverno', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0
    except subprocess.CalledProcessError:
        return False

def is_falco_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'falco', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0
    except subprocess.CalledProcessError:
        return False



###############################################################################################################
# end
###############################################################################################################




#################################################################################################
#        TOOLS
###################################################################################################



@app.route('/tools/<cluster_name>', methods=['GET', 'POST', 'DELETE'])
def tools(cluster_name):
    if request.method == 'POST':
        data = request.json  # Access JSON data from the request body
        selected_tool = data.get('tool')  # Get the tool information

        try:
            context_name = f"kind-{cluster_name}"
            subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
            if selected_tool == 'kafka':
                # Install Kafka
                if is_kafka_installed():
                    return jsonify({'success': True, 'message': 'Kafka is already installed'})
                subprocess.run(['kubectl', 'create', 'namespace', 'kafka'], check=True)
                subprocess.run(['kubectl', 'create', '-f', 'https://strimzi.io/install/latest?namespace=kafka', '-n', 'kafka'], check=True)
                subprocess.run(['kubectl', 'apply', '-f', 'https://strimzi.io/examples/latest/kafka/kafka-persistent-single.yaml', '-n', 'kafka'], check=True)
                subprocess.run(['kubectl', 'wait', 'kafka/my-cluster', '--for=condition=Ready', '--timeout=300s', '-n', 'kafka'], check=True)

                return jsonify({'success': True, 'message': 'Kafka installed successfully'})
            elif selected_tool == 'falco':
                # Install Falco
                if is_fal_installed():
                    return jsonify({'success': True, 'message': 'Falco is already installed'})
                subprocess.run(['kubectl', 'create', 'namespace', 'falco'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'falcosecurity', 'https://falcosecurity.github.io/charts'], check=True)
                subprocess.run(['helm', 'repo', 'update'], check=True)
                webhook_url_base64 = "aHR0cHM6Ly9ob29rcy5zbGFjay5jb20vc2VydmljZXMvVDA0QUhTRktMTTgvQjA1SzA3NkgyNlMvV2ZHRGQ5MFFDcENwNnFzNmFKNkV0dEg4"
                webhook_url = base64.b64decode(webhook_url_base64).decode('utf-8')
                command = [
                    'helm', 'install', 'falco', '-n', 'falco',
                    '--set', 'driver.kind=ebpf',
                    '--set', 'tty=true',
                    'falcosecurity/falco',
                    '--set', 'falcosidekick.enabled=true',
                    f'--set', f'falcosidekick.config.slack.webhookurl={webhook_url}',
                    '--set', 'falcosidekick.config.slack.minimumpriority=notice',
                    '--set', 'falcosidekick.config.customfields="user:arunvel"'
                ]
                subprocess.run(command, check=True)
                return jsonify({'success': True, 'message': 'Falco installed successfully'})
            else:
                return jsonify({'success': False, 'error': 'Invalid tool selected'})
        except subprocess.CalledProcessError as e:
            return jsonify({'success': False, 'message': f'Error: {str(e)}'})

    elif request.method == 'DELETE':
        data = request.json  # Access JSON data from the request body
        selected_tool = data.get('tool')  # Get the tool information

        try:
            context_name = f"kind-{cluster_name}"
            subprocess.run(['kubectl', 'config', 'use-context', context_name], check=True)
            if selected_tool == 'kafka':
                if not is_kafka_installed():
                    return jsonify({'success': True, 'message': 'Kafka is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'kafka'], check=True)
                return jsonify({'success': True, 'message': 'Kafka deleted successfully'})
            elif selected_tool == 'falco':
                if not is_fal_installed():
                    return jsonify({'success': True, 'message': 'Falco is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'falco'], check=True)
                return jsonify({'success': True, 'message': 'Falco deleted successfully'})
            else:
                return jsonify({'success': False, 'error': 'Invalid tool selected'})
        except subprocess.CalledProcessError as e:
            return jsonify({'success': False, 'message': f'Error: {str(e)}'})
    
    else:
        return render_template('tools.html', cluster_name=cluster_name)


def is_kafka_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'kafka', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0
    except subprocess.CalledProcessError:
        return False

def is_fal_installed():
    try:
        result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'falco', '-o', 'json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        output = result.stdout.decode('utf-8')
        pods_info = json.loads(output)
        return len(pods_info.get('items', [])) > 0
    except subprocess.CalledProcessError:
        return False


#######################################################################################################
# TOOLS --------------------------------------------------END
############################################################################################################







@app.route('/get_pods', methods=['POST'])
def get_pods():
    if request.method == 'POST':
        try:
            namespace = request.json['namespace']
            pods = get_pods(namespace)
            return jsonify({'pods': pods})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify({'error': 'Method not allowed'}), 405


######################################################################################################
############# logs
####################################################################################################
try:
    # Try to load the kubeconfig
    config.load_kube_config()
    print("Kubeconfig loaded successfully")
except ConfigException as e:
    # Handle the case when the kubeconfig is not found or is invalid
    print(f"Kubeconfig not found or invalid: {str(e)}")
    print("Continuing without kubeconfig...")





# Function to get namespaces
def get_namespaces():
    v1 = client.CoreV1Api()
    namespaces = v1.list_namespace().items
    return [ns.metadata.name for ns in namespaces]

# Function to get pods in a namespace
def get_pods(namespace):
    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace).items
    return [pod.metadata.name for pod in pods]

# Function to fetch logs for a pod
def get_pod_logs(namespace, pod_name):
    v1 = client.CoreV1Api()
    logs = v1.read_namespaced_pod_log(pod_name, namespace)
    return logs

@app.route('/logs', methods=['GET', 'POST'])
def logs():
    if request.method == 'POST':
        namespace = request.form['namespace']
        pod_name = request.form['pod_name']
        logs = get_pod_logs(namespace, pod_name)
        return jsonify({'logs': logs})
    else:
        namespaces = get_namespaces()
        return render_template('logs.html', namespaces=namespaces)





# Route to fetch secrets in a namespace
@app.route('/get_secrets', methods=['POST'])
def get_secrets():
    namespace = request.json['namespace']
    secrets = get_secrets_for_namespace(namespace)
    return jsonify({'secrets': secrets})

# Route to fetch config maps in a namespace
@app.route('/get_configmaps', methods=['POST'])
def get_configmaps():
    namespace = request.json['namespace']
    configmaps = get_configmaps_for_namespace(namespace)
    return jsonify({'configmaps': configmaps})

# Route to fetch deployments in a namespace
@app.route('/get_deployments', methods=['POST'])
def get_deployments():
    namespace = request.json['namespace']
    deployments = get_deployments_for_namespace(namespace)
    return jsonify({'deployments': deployments})

# Route to fetch ingresses in a namespace
@app.route('/get_ingresses', methods=['POST'])
def get_ingresses():
    namespace = request.json['namespace']
    ingresses = get_ingresses_for_namespace(namespace)
    return jsonify({'ingresses': ingresses})

# Route to fetch persistent volumes (PV) in a namespace
@app.route('/get_pvs', methods=['POST'])
def get_pvs():
    pvs = get_pvs_from_cluster()
    return jsonify({'pvs': pvs})

# Route to fetch persistent volume claims (PVC) in a namespace
@app.route('/get_pvcs', methods=['POST'])
def get_pvcs():
    namespace = request.json['namespace']
    pvcs = get_pvcs_for_namespace(namespace)
    return jsonify({'pvcs': pvcs})

# Route to fetch jobs in a namespace
@app.route('/get_jobs', methods=['POST'])
def get_jobs():
    namespace = request.json['namespace']
    jobs = get_jobs_for_namespace(namespace)
    return jsonify({'jobs': jobs})

# Route to fetch cron jobs in a namespace
@app.route('/get_cronjobs', methods=['POST'])
def get_cronjobs():
    namespace = request.json['namespace']
    cronjobs = get_cronjobs_for_namespace(namespace)
    return jsonify({'cronjobs': cronjobs})

@app.route('/get_services', methods=['GET'])
def get_services():
    namespace = request.args.get('namespace')
    if namespace:
        services = get_services_for_namespace(namespace)
        return jsonify({'services': services})
    else:
        return jsonify({'error': 'Namespace not provided'}), 400

# Function to get services for a namespace
def get_services_for_namespace(namespace):
    core_v1 = client.CoreV1Api()
    try:
        services = core_v1.list_namespaced_service(namespace)
        return [service.metadata.name for service in services.items]
    except client.rest.ApiException as e:
        print(f"Error retrieving services for namespace '{namespace}': {str(e)}")
        return []

# Function to get secrets for a namespace
def get_secrets_for_namespace(namespace):
    secrets = api_instance.list_namespaced_secret(namespace)
    return [secret.metadata.name for secret in secrets.items]

# Function to get config maps for a namespace
def get_configmaps_for_namespace(namespace):
    configmaps = api_instance.list_namespaced_config_map(namespace)
    return [configmap.metadata.name for configmap in configmaps.items]

# Function to get deployments for a namespace
def get_deployments_for_namespace(namespace):
    apps_v1 = client.AppsV1Api()
    deployments = apps_v1.list_namespaced_deployment(namespace)
    return [deployment.metadata.name for deployment in deployments.items]

# Function to get ingresses for a namespace
def get_ingresses_for_namespace(namespace):
    networking_v1 = client.NetworkingV1Api()
    ingresses = networking_v1.list_namespaced_ingress(namespace)
    return [ingress.metadata.name for ingress in ingresses.items]

# Function to get persistent volumes (PV) from the cluster
def get_pvs_from_cluster():
    pvs = api_instance.list_persistent_volume()
    return [pv.metadata.name for pv in pvs.items]

# Function to get persistent volume claims (PVC) for a namespace
def get_pvcs_for_namespace(namespace):
    pvcs = api_instance.list_namespaced_persistent_volume_claim(namespace)
    return [pvc.metadata.name for pvc in pvcs.items]

# Function to get jobs for a namespace
def get_jobs_for_namespace(namespace):
    batch_v1 = client.BatchV1Api()
    jobs = batch_v1.list_namespaced_job(namespace)
    return [job.metadata.name for job in jobs.items]

# Function to get cron jobs for a namespace
def get_cronjobs_for_namespace(namespace):
    batch_v1 = client.BatchV1beta1Api()
    cronjobs = batch_v1.list_namespaced_cron_job(namespace)
    return [cronjob.metadata.name for cronjob in cronjobs.items]



# Kubernetes API client
api_instance = client.CoreV1Api()

# List of resource types
resource_types = ['pod', 'service', 'deployment', 'ingress', 'configmap', 'secret']

# Route to render the HTML template
@app.route('/delete_resource', methods=['GET'])
def delete_resource_form():
    namespaces = get_namespaces()
    return render_template('delete_resource.html', namespaces=namespaces, resource_types=resource_types)

# Route to handle form submission
@app.route('/delete_resource', methods=['POST'])
def delete_resource():
    namespace = request.form['namespace']
    resource_type = request.form['resource_type']
    resource_name = request.form['resource_name']

    if not namespace or not resource_type or not resource_name:
        return 'Incomplete form data', 400

    if resource_type not in resource_types:
        return 'Invalid resource type', 400

    try:
        if resource_type == 'pod':
            delete_pod(namespace, resource_name)
        elif resource_type == 'service':
            delete_service(namespace, resource_name)
        elif resource_type == 'deployment':
            delete_deployment(namespace, resource_name)
        elif resource_type == 'ingress':
            delete_ingress(namespace, resource_name)
        elif resource_type == 'configmap':
            delete_configmap(namespace, resource_name)
        elif resource_type == 'secret':
            delete_secret(namespace, resource_name)
        return render_template('delete_resource.html', message=f'Resource deleted successfully: {resource_type} {resource_name} in namespace {namespace}', namespaces=get_namespaces(), resource_types=resource_types)
    except Exception as e:
        return render_template('delete_resource.html', error=f'Error deleting resource: {str(e)}', namespaces=get_namespaces(), resource_types=resource_types), 500

# Function to get namespaces
def get_namespaces():
    return [ns.metadata.name for ns in api_instance.list_namespace().items]

# Function to delete a pod
def delete_pod(namespace, pod_name):
    api_instance.delete_namespaced_pod(pod_name, namespace)

# Function to delete a service
def delete_service(namespace, service_name):
    api_instance.delete_namespaced_service(service_name, namespace)

# Function to delete a deployment
def delete_deployment(namespace, deployment_name):
    apps_v1 = client.AppsV1Api()
    apps_v1.delete_namespaced_deployment(deployment_name, namespace)

# Function to delete an ingress
def delete_ingress(namespace, ingress_name):
    networking_v1 = client.NetworkingV1Api()
    networking_v1.delete_namespaced_ingress(ingress_name, namespace)

# Function to delete a configmap
def delete_configmap(namespace, configmap_name):
    api_instance.delete_namespaced_config_map(configmap_name, namespace)

# Function to delete a secret
def delete_secret(namespace, secret_name):
    api_instance.delete_namespaced_secret(secret_name, namespace)


##################################################################################################################
###### ATTACH
##################################################################################################################



##################################################################################################################
###### ATTACH --------------------------------END
##################################################################################################################





##################################################################################################################
###### DESCRIPTION 
##################################################################################################################





# Function to get namespaces
def get_namespaces():
    v1 = client.CoreV1Api()
    namespaces = v1.list_namespace().items
    return [ns.metadata.name for ns in namespaces]

# Function to get resources in a namespace based on resource type
def get_deployments(namespace):
    api_instance = client.AppsV1Api()
    deployments = api_instance.list_namespaced_deployment(namespace).items
    return [deployment.metadata.name for deployment in deployments]

# Function to get ingresses in a namespace
def get_ingresses(namespace):
    api_instance = client.CoreV1Api()
    ingresses = api_instance.list_namespaced_ingress(namespace).items
    return [ingress.metadata.name for ingress in ingresses]

# Function to get services in a namespace
def get_services(namespace):
    api_instance = client.CoreV1Api()
    services = api_instance.list_namespaced_service(namespace).items
    return [service.metadata.name for service in services]

# Function to get statefulsets in a namespace
def get_statefulsets(namespace):
    api_instance = client.AppsV1Api()
    statefulsets = api_instance.list_namespaced_stateful_set(namespace).items
    return [statefulset.metadata.name for statefulset in statefulsets]

# Function to get daemonsets in a namespace
def get_daemonsets(namespace):
    api_instance = client.AppsV1Api()
    daemonsets = api_instance.list_namespaced_daemon_set(namespace).items
    return [daemonset.metadata.name for daemonset in daemonsets]

# Function to get resources in a namespace based on resource type
# Function to get resources in a namespace based on resource type
def get_resources(namespace, resource_type):
    if resource_type == 'pod':
        v1 = client.CoreV1Api()
        resources = v1.list_namespaced_pod(namespace).items
        return [resource.metadata.name for resource in resources]
    elif resource_type == 'deployment':
        return get_deployments(namespace)
    elif resource_type == 'ingress':
        return get_ingresses(namespace)
    elif resource_type == 'service':
        return get_services(namespace)
    elif resource_type == 'statefulset':
        return get_statefulsets(namespace)
    elif resource_type == 'daemonset':
        return get_daemonsets(namespace)
    # Add other resource types as needed
    else:
        return []


# Route to fetch namespace list using Kubernetes API
@app.route('/get_namespaces', methods=['GET'])
def get_namespaces_route():
    try:
        namespaces = get_namespaces()
        return jsonify({'namespaces': namespaces})
    except Exception as e:
        print(f"Exception when fetching namespaces: {e}")
        return jsonify({'error': str(e)})

# Route to fetch resources based on namespace and resource type
@app.route('/get_resources', methods=['POST'])
def get_resources_route():
    try:
        data = request.json
        namespace = data.get('namespace')
        resource_type = data.get('resource_type')

        resource_names = get_resources(namespace, resource_type)

        return jsonify({'resource_names': resource_names})
    except Exception as e:
        print(f"Exception when fetching resources: {e}")
        return jsonify({'error': str(e)})

# Route to render the form
@app.route('/describe/<cluster_name>', methods=['GET', 'POST'])
def describe(cluster_name):
    if request.method == 'POST':
        namespace = request.form['namespace']
        resource_type = request.form['resource_type']
        resource_name = request.form['resource_name']

        try:
            # Run the kubectl describe command for the specified resource
            result = subprocess.run(['kubectl', 'describe', resource_type, resource_name, '-n', namespace], capture_output=True, text=True)
            description = result.stdout
        except Exception as e:
            description = f"Error describing {resource_type}: {e}"

        return render_template('describe.html', cluster_name=cluster_name, description=description)
    
    # Add a default return statement for the GET method
    return render_template('describe.html')



import re

@app.route('/kafka/', methods=['GET'])
def kafka_cluster_details():
    try:
        # Run the kubectl command to get details of the Kafka cluster
        result = subprocess.run(['kubectl', 'get', 'kafka', '-n', 'strimzi'], capture_output=True, check=True, text=True)
        kafka_output = result.stdout
        print(kafka_output)

        # Use regular expressions to extract the relevant details
        pattern = re.compile(r'(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s*(\S+)?')
        match = pattern.search(kafka_output)
        if match:
            kafka_cluster_name = match.group(1)
            desired_kafka_replicas = int(match.group(2))
            desired_zk_replicas = int(match.group(3))
            ready = match.group(4) == 'True'
            warnings = match.group(5) if match.group(5) else ""

            # Construct the response
            response = {
                'success': True,
                'kafka_cluster_name': kafka_cluster_name,
                'desired_kafka_replicas': desired_kafka_replicas,
                'desired_zk_replicas': desired_zk_replicas,
                'ready': ready,
                'warnings': warnings
            }

            return render_template('kafka_cluster.html', data=response)
        else:
            raise ValueError("Data does not match expected format")

    except (subprocess.CalledProcessError, ValueError) as e:
        error_message = f"Error retrieving Kafka cluster details: {str(e)}"
        return jsonify({'success': False, 'error': error_message})



@app.route('/kafka/create_topic', methods=['POST'])
def create_topic():
    try:
        topic_name = request.form['topic_name']
        partitions = request.form['partitions']
        replicas = request.form['replicas']

        # Define the YAML template for creating Kafka topic
        yaml_template = f"""
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaTopic
metadata:
  name: {topic_name}
  namespace: strimzi
  labels:
    strimzi.io/cluster: my-cluster
spec:
  partitions: {partitions}
  replicas: {replicas}
  config:
    retention.ms: 7200000
    segment.bytes: 1000000
"""
        # Apply the YAML content using kubectl
        result = subprocess.run(['kubectl', 'apply', '-f', '-'], input=yaml_template, capture_output=True, check=True, text=True)
        return render_template('create_topic.html', success=True, message=result.stdout)
    except Exception as e:
        return render_template('create_topic.html',cluster_name=cluster_name, success=False, error=str(e))







@app.route('/kafka/delete_topic', methods=['POST'])
def delete_topic():
    try:
        # Get the selected topic name from the form
        topic_name = request.form['topic_name']

        # Check if the topic exists before attempting to delete it
        check_result = subprocess.run(['kubectl', 'get', 'kafkatopic', topic_name, '-n', 'strimzi'], capture_output=True, text=True)
        
        # Check if the command was successful and if the topic exists
        if check_result.returncode == 0 and check_result.stdout.strip():
            # Run the command to delete the Kafka topic
            delete_result = subprocess.run(['kubectl', 'delete', 'kafkatopic', topic_name, '-n', 'strimzi'], capture_output=True, text=True)

            # Check if the command was successful
            if delete_result.returncode == 0:
                return jsonify({'success': True, 'message': f'Topic "{topic_name}" deleted successfully.'})
            else:
                return jsonify({'success': False, 'error': f'Failed to delete topic "{topic_name}". Error: {delete_result.stderr}'})
        else:
            return jsonify({'success': False, 'error': f'Topic "{topic_name}" not found.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})








@app.route('/kafka/topics', methods=['GET'])
def list_topics():
    try:
        # Run the command to get the list of Kafka topics
        result = subprocess.run(['kubectl', 'get', 'kafkatopic', '-n', 'strimzi'], capture_output=True, check=True, text=True)

        # Extract topic names from the command output
        topics = [line.split()[0] for line in result.stdout.strip().split('\n')[1:]]

        return jsonify({'success': True, 'topics': topics})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0






from flask import render_template

@app.route('/kafka/deploy_app', methods=['POST'])
def deploy_kafka_app():
    try:
        # Check if Kafka is already deployed
        if is_kafka_deployed():
            return jsonify({'success': False, 'error': 'Kafka is already deployed.'})

        # Create the kafka-app namespace if it doesn't exist
        create_namespace_if_not_exists('kafka-app')

        # Deploy Kafka application
        subprocess.run(['kubectl', 'apply', '-f', './tools/kafka/deploy_app.yaml', '-n', 'kafka-app'], check=True)

        # Wait for Kafka pods to come up
        time.sleep(15)  # Adjust this delay as needed

        # Generate a random port number between 9000 and 9999
        kafka_port = random.randint(9000, 9999)

        # Perform port forwarding with the random port
        subprocess.Popen(['kubectl', 'port-forward', 'svc/ecomm-web-app-service', f'{kafka_port}:80', '-n', 'kafka-app'])

        # Construct Kafka URL
        kafka_url = f'http://localhost:{kafka_port}'

        return render_template('kafka_deployed.html', kafka_url=kafka_url)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})




@app.route('/kafka/delete_app', methods=['POST'])
def delete_kafka_app():
    try:
        # Delete the kafka-app namespace
        subprocess.run(['kubectl', 'delete', 'namespace', 'kafka-app'], check=True)
        return jsonify({'success': True, 'message': 'Kafka Ecomm Application namespace deleted successfully.'})
    except subprocess.CalledProcessError as e:
        return jsonify({'success': False, 'error': str(e)})


def is_kafka_deployed():
    # Check if Kafka pods are running in kafka-app namespace
    result = subprocess.run(['kubectl', 'get', 'pods', '-n', 'kafka-app'], capture_output=True, text=True)
    return 'kafka-' in result.stdout and 'Running' in result.stdout

def create_namespace_if_not_exists(namespace):
    # Check if namespace exists, if not create it
    result = subprocess.run(['kubectl', 'get', 'namespace', namespace], capture_output=True, text=True)
    if 'NotFound' in result.stderr:
        subprocess.run(['kubectl', 'create', 'namespace', namespace], check=True)











@app.route('/jaeger', methods=['GET'])
def jaeger():
    instance_ip = get_instance_ip()
    if instance_ip == 'localhost':
        dashboard_url = 'http://localhost:16686'
    else:
        dashboard_url = f'http://{instance_ip}:16686'
    return render_template('jaeger.html', dashboard_url=dashboard_url)



import random

@app.route('/jaeger/dashboard', methods=['GET'])
def jaeger_dashboard():
    try:
        # Randomly select a port between 15000 and 15999
        jaeger_port = random.randint(15000, 15999)
        
        if is_port_in_use(jaeger_port):
            print(f"Port {jaeger_port} is already in use, skipping port forwarding.")
        else:
            subprocess.Popen(['kubectl', 'port-forward', 'svc/simplest-query', f'{jaeger_port}:16686', '-n', 'observability', '--address', '0.0.0.0'])

        instance_ip = "localhost"  # You may adjust this based on your configuration
        if instance_ip == 'localhost':
            dashboard_url = f'http://localhost:{jaeger_port}'
        else:
            dashboard_url = f'http://public-ip:{jaeger_port}'
        
        return render_template('jaeger_dashboard.html', dashboard_url=dashboard_url)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error port-forwarding Jaeger query service: {str(e)}'}), 500


@app.route('/jaeger/deploy_app', methods=['POST'])
def deploy_jaeger_app():
    try:
        # Check if the sample app is already deployed
        result = subprocess.run(['kubectl', 'get', 'deployment', 'service-b', '-n', 'observability'], capture_output=True, text=True)
        if 'sample-app' in result.stdout:
            return jsonify({'success': True, 'message': 'Sample application is already deployed.'})

        # Deploy the sample application for testing Jaeger
        subprocess.run(['kubectl', 'apply', '-f', 'jaeger/sample-app.yaml', '-n', 'observability'], check=True)
        
        # Render the HTML template after deploying the sample application
        return render_template('deploy_jaeger_app.html', message='Sample application deployed successfully.')

    except subprocess.CalledProcessError as e:
        return jsonify({'success': False, 'error': f'Error deploying sample application: {str(e)}'}), 500


import random




@app.route('/airflow', methods=['GET'])
def airflow():
    instance_ip = get_instance_ip()
    if instance_ip == 'localhost':
        dashboard_url_airflow = 'http://localhost:8080'  # Default Airflow port
    else:
        dashboard_url_airflow = f'http://{instance_ip}:8080'  # Adjust port if necessary
    return render_template('airflow.html', dashboard_url_airflow=dashboard_url_airflow)

@app.route('/airflow/dashboard', methods=['GET'])
def airflow_dashboard():
    try:
        # Randomly select a port between 16000 and 16999
        airflow_port = random.randint(16000, 16999)
        
        if is_port_in_use(airflow_port):
            print(f"Port {airflow_port} is already in use, skipping port forwarding.")
        else:
            subprocess.Popen(['kubectl', 'port-forward', 'svc/my-airflow-webserver', f'{airflow_port}:8080', '-n', 'airflow', '--address', '0.0.0.0'])

        instance_ip = get_instance_ip()  # Get the instance IP
        if instance_ip == 'localhost':
            dashboard_url_airflow = f'http://localhost:{airflow_port}'
        else:
            dashboard_url_airflow = f'http://{instance_ip}:{airflow_port}'
        
        return render_template('airflow_dashboard.html', dashboard_url_airflow=dashboard_url_airflow)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error port-forwarding Airflow web service: {str(e)}'}), 500





@app.route('/tekton', methods=['GET'])
def tekton():
    instance_ip = get_instance_ip()
    if instance_ip == 'localhost':
        dashboard_url_tekton = 'http://localhost:9097'
    else:
        dashboard_url_tekton = f'http://{instance_ip}:9097'
    return render_template('tekton.html', dashboard_url_tekton=dashboard_url_tekton)





@app.route('/tekton/dashboard', methods=['GET'])
def tekton_dashboard():
    try:
        # Randomly select a port between 9000 and 9999
        tekton_port = random.randint(9000, 9999)
        
        if is_port_in_use(tekton_port):
            print(f"Port {tekton_port} is already in use, skipping port forwarding.")
        else:
            subprocess.Popen(['kubectl', 'port-forward', 'svc/tekton-dashboard', f'{tekton_port}:9097', '-n', 'tekton-pipelines', '--address', '0.0.0.0'])

        instance_ip = "localhost"  # You may adjust this based on your configuration
        if instance_ip == 'localhost':
            dashboard_url_tekton = f'http://localhost:{tekton_port}'
        else:
            dashboard_url_tekton = f'http://public-ip:{tekton_port}'
        
        return render_template('tekton_dashboard.html', dashboard_url_tekton=dashboard_url_tekton)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error port-forwarding Tekton dashboard service: {str(e)}'}), 500





# Tekton Build route
@app.route('/tekton/build', methods=['GET', 'POST'])
def tekton_build():
    if request.method == 'POST':
        build_type = request.form.get('build_type')
        if build_type == 'simple':
            # Handle simple build pipeline
            return render_template('simple_build.html')
        elif build_type == 'complex':
            # Handle complex build pipeline
            return render_template('complex_build.html')

    return render_template('build_type.html')







@app.route('/generate_template', methods=['GET', 'POST'])
def generate_template():
    if request.method == 'GET':
        return render_template('create_pipeline_popup.html')
    elif request.method == 'POST':
        git_url = request.form.get('git_url')
        docker_registry = request.form.get('docker_registry')       
        git_username = request.form.get('git_username')
        git_token = request.form.get('git_token')
        docker_username = request.form.get('docker_username')
        docker_token = request.form.get('docker_token')

        # Check for missing form fields
        missing_fields = [field for field in [git_url, docker_registry, git_username, git_token, docker_username, docker_token] if not field]
        if missing_fields:
            return f"Error: Missing form fields - {', '.join(missing_fields)}"

        # Store the form data in session or database for later use
        return redirect(url_for('create_pipeline_simple'))

@app.route('/create_pipeline_simple', methods=['GET', 'POST'])
def create_pipeline_simple():
    if request.method == 'GET':
        return "Invalid request method. Please submit the form."
    elif request.method == 'POST':
        git_url = request.form.get('git_url')
        docker_registry = request.form.get('docker_registry')
        #image_name = request.form.get('image_name')
        git_username = request.form.get('git_username')
        git_token = request.form.get('git_token')
        docker_username = request.form.get('docker_username')
        docker_token = request.form.get('docker_token')

        # Check if any form fields are missing
        if None in [git_url, docker_registry, git_username, git_token, docker_username, docker_token]:
            return "Error: Missing form fields"

        # Apply Git and Docker configurations using subprocess and kubectl apply
        subprocess.run(['kubectl', 'create', 'secret', 'generic', 'git-credentials', '--from-literal=username='+git_username, '--from-literal=password='+git_token])
        subprocess.run(['kubectl', 'create', 'secret', 'generic', 'docker-credentials', '--from-literal=username='+docker_username, '--from-literal=password='+docker_token])

        # Apply the Pipeline and PipelineRun YAML configurations using kubectl apply
        subprocess.run(['kubectl', 'apply', '-f', './tools/ci/tasks/git-clone.yaml'])
        subprocess.run(['kubectl', 'apply', '-f', './tools/ci/tasks/build-push.yaml'])
        subprocess.run(['kubectl', 'apply', '-f', './tools/ci/pipeline/pipeline-simple.yaml'])
        subprocess.run(['kubectl', 'apply', '-f', './tools/ci/pipeline/pipeline-run-simple.yaml'])

        return "Kubernetes configurations applied successfully!"


#######################################################
# /argo
#########################################################



@app.route('/argocd', methods=['GET'])
def argocd():
    instance_ip = get_instance_ip()
    if instance_ip == 'localhost':
        dashboard_url_argocd = 'http://localhost:9098'
    else:
        dashboard_url_argocd = f'http://{instance_ip}:9098'
    return render_template('argocd.html', dashboard_url_argocd=dashboard_url_argocd)



@app.route('/argocd/dashboard', methods=['GET'])
def argocd_dashboard():
    try:
        # Randomly select a port between 9000 and 9999
        argocd_port = random.randint(9000, 9999)
        
        if is_port_in_use(argocd_port):
            print(f"Port {argocd_port} is already in use, skipping port forwarding.")
        else:
            subprocess.Popen(['kubectl', 'port-forward', 'svc/argocd-server', f'{argocd_port}:443', '-n', 'argocd', '--address', '0.0.0.0'])

        instance_ip = "localhost"  # You may adjust this based on your configuration
        if instance_ip == 'localhost':
            dashboard_url_argocd = f'http://localhost:{argocd_port}'
        else:
            dashboard_url_argocd = f'http://public-ip:{argocd_port}'
        
        return render_template('argocd_dashboard.html', dashboard_url_argocd=dashboard_url_argocd)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error port-forwarding ArgoCD dashboard service: {str(e)}'}), 500


#######################################################
# /argo ------------------------------END
#########################################################

@app.route('/chaosmesh', methods=['GET'])
def chaosmesh():
    instance_ip = "localhost"
    if instance_ip == 'localhost':
        dashboard_url_chaosmesh = 'http://localhost:2333'
    else:
        dashboard_url_chaosmesh = f'http://{instance_ip}:2333'
    return render_template('chaosmesh.html', dashboard_url_chaosmesh=dashboard_url_chaosmesh)


@app.route('/chaosmesh/dashboard', methods=['GET'])
def chaosmesh_dashboard():
    try:
        # Randomly select a port between 9000 and 9999
        chaosmesh_port = random.randint(9000, 9999)
        
        if is_port_in_use(chaosmesh_port):
            print(f"Port {chaosmesh_port} is already in use, skipping port forwarding.")
        else:
            subprocess.Popen(['kubectl', 'port-forward', 'svc/chaos-dashboard', f'{chaosmesh_port}:2333', '-n', 'chaos-mesh', '--address', '0.0.0.0'])

        instance_ip = "localhost"  # You may adjust this based on your configuration
        if instance_ip == 'localhost':
            dashboard_url_chaosmesh = f'http://localhost:{chaosmesh_port}'
        else:
            dashboard_url_chaosmesh = f'http://public-ip:{chaosmesh_port}'
        
        return render_template('chaosmesh_dashboard.html', dashboard_url_chaosmesh=dashboard_url_chaosmesh)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error port-forwarding Chaos Mesh dashboard service: {str(e)}'}), 500






#######################################################
# /grafana -----------------------------
#########################################################
import random


# Function to check if a port is in use
def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

# Function to get an available port for port forwarding
def get_available_port():
    port = random.randint(8000, 9999)  # Modify port range as needed
    while is_port_in_use(port):
        port = random.randint(8000, 9999)  # Modify port range as needed
    return port


@app.route('/grafana', methods=['GET'])
def grafana():
    instance_ip = get_instance_ip()
    if instance_ip == 'localhost':
        dashboard_url_grafana = 'http://localhost:3000'
    else:
        dashboard_url_grafana = f'http://{instance_ip}:3000'
    return render_template('grafana.html', dashboard_url_grafana=dashboard_url_grafana)


@app.route('/grafana/dashboard', methods=['GET'])
def grafana_dashboard():
    try:
        port = get_available_port()
        subprocess.Popen(['kubectl', 'port-forward', 'svc/prometheus-grafana', f'{port}:80', '-n', 'monitoring', '--address', '0.0.0.0'])
        dashboard_url_grafana = f'http://localhost:{port}'
        return render_template('grafana_dashboard.html', dashboard_url_grafana=dashboard_url_grafana)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error port-forwarding Grafana dashboard service: {str(e)}'}), 500



#######################################################
# /grafana -----------------------------  END
#########################################################





@app.route('/buildpacks', methods=['GET', 'POST'])
def buildpacks():
    if request.method == 'GET':
        return render_template('buildpacks.html')
    elif request.method == 'POST':
        github_url = request.form.get('github_url')
        if github_url:
            try:
                # Clone the repository
                clone_command = f'git clone {github_url} app'
                subprocess.run(clone_command, shell=True, check=True)

                # Change to the app directory
                subprocess.run('cd app', shell=True, check=True)

                # Suggest a builder
                suggest_command = 'pack builder suggest'
                suggest_result = subprocess.run(suggest_command, shell=True, capture_output=True, text=True)
                suggested_builder = suggest_result.stdout.strip()

               

                return render_template('builder_info.html', suggested_builder=suggested_builder)
            except subprocess.CalledProcessError as e:
                return jsonify({'success': False, 'error': str(e)}), 500
        else:
            return jsonify({'success': False, 'error': 'Please provide a GitHub URL.'}), 400

    elif request.method == 'POST' and request.form.get('confirm_build'):
        suggested_builder = request.form.get('suggested_builder')
        if suggested_builder:
            try:
                # Build the app using pack
                build_command = f'pack build app --builder {suggested_builder}'
                subprocess.run(build_command, shell=True, check=True)

                return jsonify({'success': True, 'message': 'App built successfully.'})
            except subprocess.CalledProcessError as e:
                return jsonify({'success': False, 'error': str(e)}), 500
        else:
            return jsonify({'success': False, 'error': 'No builder selected.'}), 400




######################################################################################
########################### trivy
###################################################################################






@app.route('/trivy', methods=['GET'])
def trivy():
    try:
        vulnerability_reports = subprocess.check_output(['kubectl', 'get', 'vulnerabilityreports', '--all-namespaces', '-o', 'wide']).decode('utf-8')
        config_audit_reports = subprocess.check_output(['kubectl', 'get', 'configauditreports', '--all-namespaces', '-o', 'wide']).decode('utf-8')
        trivy_operator_logs = subprocess.check_output(['kubectl', 'logs', '-n', 'trivy-system', 'deployment/trivy-operator']).decode('utf-8')
        infra_assessment_reports = subprocess.check_output(['kubectl', 'get', 'infraassessmentreports', '--all-namespaces', '-o', 'wide']).decode('utf-8')
        rbac_assessment_reports = subprocess.check_output(['kubectl', 'get', 'rbacassessmentreports', '--all-namespaces', '-o', 'wide']).decode('utf-8')
        exposed_secrets_report = subprocess.check_output(['kubectl', 'get', 'exposedsecretreport', '--all-namespaces', '-o', 'wide']).decode('utf-8')
        cluster_compliance_report = subprocess.check_output(['kubectl', 'get', 'clustercompliancereport', '--all-namespaces', '-o', 'wide']).decode('utf-8')

        return render_template('trivy.html', 
                                vulnerability_reports=vulnerability_reports,
                                config_audit_reports=config_audit_reports,
                                trivy_operator_logs=trivy_operator_logs,
                                infra_assessment_reports=infra_assessment_reports,
                                rbac_assessment_reports=rbac_assessment_reports,
                                exposed_secrets_report=exposed_secrets_report,
                                cluster_compliance_report=cluster_compliance_report)
    except Exception as e:
        return f"Error: {str(e)}"




##################################################################################################################
###### END
##################################################################################################################

if __name__ == '__main__':
    create_database()
    app.run(host='0.0.0.0',port=5000,debug=True)
    
