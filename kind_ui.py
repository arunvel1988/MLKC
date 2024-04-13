from flask import Flask, render_template, request,jsonify, redirect, url_for
import sqlite3
import subprocess
import yaml
import json
import threading
import os
import base64
from kubernetes import client, config


app = Flask(__name__)

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

# Generate Kind cluster configuration YAML
def generate_kind_config(name, num_nodes):
    config = {
        "kind": "Cluster",
        "apiVersion": "kind.x-k8s.io/v1alpha4",
        "nodes": [{"role": "control-plane"}] + [{"role": "worker"} for _ in range(num_nodes - 1)]
    }
    with open(f"kind-config-{name}.yaml", "w") as file:
        yaml.dump(config, file)

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

    # Get clusters using kind get clusters command
    kind_output = subprocess.check_output(['kind', 'get', 'clusters']).decode('utf-8')
    kind_clusters = kind_output.strip().split('\n') if kind_output.strip() else []

    return render_template('list_clusters.html', db_clusters=db_clusters, kind_clusters=kind_clusters)

@app.route('/create_cluster', methods=['GET', 'POST'])
def create_cluster():
    if request.method == 'POST':
        name = request.form['name']
        k8s_version = request.form['k8s_version']
        num_nodes = int(request.form['num_nodes'])

        if cluster_exists(name):
            error = f"Cluster with name '{name}' already exists."
            return render_template('create_cluster.html', error=error)

        # Generate Kind cluster configuration YAML
        generate_kind_config(name, num_nodes)

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




@app.route('/delete_cluster', methods=['POST'])
def delete_cluster():
    name = request.form['name']

    # Delete the Kind cluster
    try:
        result = subprocess.run(['kind', 'delete', 'cluster', '--name', name], check=True, capture_output=True, text=True)
        print(f"Kind cluster '{name}' deleted successfully.")
        print(f"Output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"Error deleting Kind cluster: {str(e)}")
        print(f"Output: {e.output}")
        # Handle the error appropriately (e.g., show an error message to the user)
        error_message = f"Failed to delete cluster '{name}'. Please check the logs for more information."
        return redirect(url_for('list_clusters', error=error_message))

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





@app.route('/get_services', methods=['GET'])
def get_services():
    namespace = request.args.get('namespace')
    services = get_services(namespace)
    return jsonify({'services': services})

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

def get_services(namespace):
    try:
        result = subprocess.run(['kubectl', 'get', 'services', '-n', namespace, '-o', 'json'], capture_output=True, check=True, text=True)
        services_json = json.loads(result.stdout)
        services = [item['metadata']['name'] for item in services_json['items']]
        return services
    except subprocess.CalledProcessError as e:
        print(f"Error retrieving services: {str(e)}")
        return []



def port_forward_thread(namespace, service_name, host_port, container_port):
    try:
        subprocess.run(['kubectl', 'port-forward', f'svc/{service_name}', f'{host_port}:{container_port}', '-n', namespace], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error during port forwarding: {str(e)}")

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
            message = f'http://localhost:{host_port}'
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
    except subprocess.CalledProcessError:
        docker_installed = False
        docker_output = 'Docker is not installed'

    # Check if kubectl is installed
    try:
        kubectl_output = subprocess.check_output(['kubectl']).decode('utf-8').strip()
        kubectl_installed = True
    except FileNotFoundError:
        kubectl_installed = False
        kubectl_output = 'kubectl is not installed'

    # Check if Kind is installed
    try:
        kind_output = subprocess.check_output(['kind', 'version']).decode('utf-8').strip()
        kind_installed = True
    except FileNotFoundError:
        kind_installed = False
        kind_output = 'Kind is not installed'

    # Check if Helm is installed
    try:
        helm_output = subprocess.check_output(['helm', 'version']).decode('utf-8').strip()
        helm_installed = True
    except subprocess.CalledProcessError:
        helm_installed = False
        helm_output = 'Helm is not installed'

    # Check if Python3 is installed
    try:
        python3_output = subprocess.check_output(['python3', '--version']).decode('utf-8').strip()
        python3_installed = True
    except FileNotFoundError:
        python3_installed = False
        python3_output = 'Python3 is not installed'

    return render_template('check_preq.html', docker_installed=docker_installed, docker_output=docker_output,
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
            elif selected_tool == 'monitoring':
                # Install Prometheus and Grafana for monitoring
                subprocess.run(['kubectl', 'create', 'namespace', 'monitoring'], check=True)
                subprocess.run(['helm', 'repo', 'add', 'prometheus-community', 'https://prometheus-community.github.io/helm-charts'], check=True)
                
                subprocess.run(['helm', 'repo', 'update'], check=True)
                subprocess.run(['helm', 'install', 'prometheus', 'prometheus-community/kube-prometheus-stack', '--namespace', 'monitoring'], check=True)

                
                subprocess.run(['helm', 'install', 'my-grafana', 'grafana/grafana', '--namespace', 'monitoring'], check=True)
                return jsonify({'success': True, 'message': 'Prometheus and Grafana installed successfully'})
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
            elif selected_tool == 'monitoring':
                # Delete ArgoCD for CD
                if not is_monitoring_installed():
                    return jsonify({'success': True, 'message': 'Monitoring is not installed'})
                subprocess.run(['kubectl', 'delete', 'ns', 'monitoring'], check=True)
                return jsonify({'success': True, 'message': 'Monitoring deleted successfully'})

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






# Load Kubernetes configuration
config.load_kube_config()

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





if __name__ == '__main__':
    create_database()
    app.run(debug=True)