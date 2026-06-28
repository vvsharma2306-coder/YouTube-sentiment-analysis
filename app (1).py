from flask import Flask, render_template, request, send_file
from googleapiclient.discovery import build
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import re, emoji, os
import plotly.express as px
import plotly.io as pio
import pandas as pd
from flask_mail import Mail, Message
import smtplib
from collections import Counter
import textstat
import nltk
from nltk.corpus import stopwords
nltk.download('stopwords')
from pytube import YouTube
import datetime

app = Flask(__name__)
API_KEY = "AIzaSyC4o4rTZU2F-_ja_hWrEs6LT4GcgwF8UD0"
youtube = build('youtube', 'v3', developerKey=API_KEY)

os.makedirs("static", exist_ok=True)

def generate_wordcloud(text_list, filename):
    try:
        text = ' '.join(text_list)
        wordcloud = WordCloud(
            width=900, height=500,
            background_color='white',
            collocations=False
        ).generate(text)
        wordcloud.to_file(os.path.join('static', filename))
    except Exception as e:
        print(f"Error generating wordcloud: {e}")



def calculate_text_stats(comments):
    # Basic stats
    total_comments = len(comments)
    avg_length = round(sum(len(comment) for comment in comments) / total_comments, 2) if total_comments > 0 else 0
    
    # Word frequency (excluding stopwords)
    stop_words = set(stopwords.words('english'))
    all_words = ' '.join(comments).lower().split()
    filtered_words = [word for word in all_words if word.isalpha() and word not in stop_words]
    word_freq = Counter(filtered_words).most_common(10)
    
    # Readability scores (average across all comments)
    readability_scores = []
    for comment in comments:
        if len(comment.split()) > 5:  # Only calculate for comments with enough words
            readability_scores.append(textstat.flesch_reading_ease(comment))
    avg_readability = round(sum(readability_scores) / len(readability_scores), 2) if readability_scores else 0
    
    # Emoji and link counts
    emoji_count = sum(emoji.emoji_count(comment) for comment in comments)
    link_count = sum(bool(re.search(r"http[s]?://\S+", comment)) for comment in comments)
    
    # Sentiment distribution
    analyzer = SentimentIntensityAnalyzer()
    sentiment_counts = {'Positive': 0, 'Negative': 0, 'Neutral': 0}
    for comment in comments:
        score = analyzer.polarity_scores(comment)['compound']
        if score > 0.05:
            sentiment_counts['Positive'] += 1
        elif score < -0.05:
            sentiment_counts['Negative'] += 1
        else:
            sentiment_counts['Neutral'] += 1
    
    return {
        'total_comments': total_comments,
        'avg_length': avg_length,
        'top_words': word_freq,
        'avg_readability': avg_readability,
        'emoji_count': emoji_count,
        'link_count': link_count,
        'sentiment_distribution': sentiment_counts
    }

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/ref')
def ref():
    return render_template('ref.html')

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route('/index', methods=['GET', 'POST'])
def index():
    return render_template('index.html')

@app.route('/search', methods=['GET', 'POST'])
def search():
    try:
        if request.method == 'POST':
            search_query = request.form['search_query']
            page_token = None
        else:
            search_query = request.args.get('query')
            page_token = request.args.get('page_token')

        search_response = youtube.search().list(
            q=search_query,
            part='id,snippet',
            maxResults=10,
            type='video',  # This already restricts to videos, but keep safety check below
            pageToken=page_token
        ).execute()

        videos = []
        for item in search_response['items']:
            # Ensure item is a video and has videoId
            if item['id']['kind'] == 'youtube#video' and 'videoId' in item['id']:
                video = {
                    'id': item['id']['videoId'],
                    'title': item['snippet']['title'],
                    'thumbnail': item['snippet']['thumbnails']['default']['url'],
                    'channel': item['snippet']['channelTitle']
                }
                videos.append(video)
            else:
                print(f"Skipped non-video item or missing videoId: {item['id']}")

        return render_template('search_results.html',
                               videos=videos,
                               query=search_query,
                               next_token=search_response.get('nextPageToken'),
                               prev_token=search_response.get('prevPageToken'))
    except Exception as e:
        return f"Error during search: {e}"
    





@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        video_url = request.form.get('video_url')
        video_id = request.form.get('video_id')
        
        if not video_url and video_id:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        if video_url:
            video_id = video_url[-11:]

        # Get video statistics
        video_response = youtube.videos().list(
            part='snippet,statistics',
            id=video_id
        ).execute()
        
        if not video_response.get('items'):
            return "Error: Video not found or unavailable"
            
        video_stats = video_response['items'][0]['snippet']
        video_stats.update(video_response['items'][0]['statistics'])
        
        uploader_channel_id = video_stats['channelId']
        video_title = video_stats['title']
        video_views = video_stats.get('viewCount', 'N/A')
        video_likes = video_stats.get('likeCount', 'N/A')
        video_comments = video_stats.get('commentCount', 'N/A')
        published_date = video_stats.get('publishedAt', 'N/A')
        
        # Format published date
        try:
            published_date = datetime.strptime(published_date, "%Y-%m-%dT%H:%M:%SZ").strftime("%B %d, %Y")
        except:
            published_date = 'N/A'

        # Get channel statistics
        channel_response = youtube.channels().list(
            part='snippet,statistics',
            id=uploader_channel_id
        ).execute()
        
        if not channel_response.get('items'):
            channel_title = 'N/A'
            channel_subs = 'N/A'
        else:
            channel_stats = channel_response['items'][0]['snippet']
            channel_stats.update(channel_response['items'][0]['statistics'])
            channel_title = channel_stats['title']
            channel_subs = channel_stats.get('subscriberCount', 'N/A')

        # Get comments
        comments, nextPageToken = [], None
        while len(comments) < 600:
            response = youtube.commentThreads().list(
                part='snippet', 
                videoId=video_id, 
                maxResults=100, 
                pageToken=nextPageToken
            ).execute()
            
            for item in response['items']:
                comment = item['snippet']['topLevelComment']['snippet']
                if comment['authorChannelId']['value'] != uploader_channel_id:
                    comments.append(comment['textDisplay'])
            
            nextPageToken = response.get('nextPageToken')
            if not nextPageToken:
                break

        # Filter comments
        hyperlink_pattern = re.compile(r"http[s]?://\S+")
        threshold_ratio = 0.65
        relevant_comments = []
        
        for text in comments:
            text = text.lower().strip()
            emojis = emoji.emoji_count(text)
            text_characters = len(re.sub(r'\s', '', text))
            if (any(char.isalnum() for char in text)) and not hyperlink_pattern.search(text):
                if emojis == 0 or (text_characters / (text_characters + emojis)) > threshold_ratio:
                    relevant_comments.append(text)

        # Save comments to file
        with open("ytcomments.txt", 'w', encoding='utf-8') as f:
            for comment in relevant_comments:
                f.write(comment + "\n")

        # Sentiment analysis with word tracking
        analyzer = SentimentIntensityAnalyzer()
        polarity, pos, neg, neu, sentiments = [], [], [], [], []
        pos_words = []
        neg_words = []
        stop_words = set(stopwords.words('english'))

        for comment in relevant_comments:
            score = analyzer.polarity_scores(comment)['compound']
            polarity.append(score)
            
            # Process words
            words = [word.lower() for word in re.findall(r'\b\w+\b', comment) 
                     if word.lower() not in stop_words and len(word) > 2 and word.isalpha()]
            
            if score > 0.05:
                pos.append(comment)
                sentiments.append("Positive")
                pos_words.extend(words)
            elif score < -0.05:
                neg.append(comment)
                sentiments.append("Negative")
                neg_words.extend(words)
            else:
                neu.append(comment)
                sentiments.append("Neutral")

        avg = round(sum(polarity) / len(polarity), 3) if polarity else 0

        # Get top positive and negative words
        top_pos_words = Counter(pos_words).most_common(10)
        top_neg_words = Counter(neg_words).most_common(10)

        # Create positive words frequency plot
        pos_words_fig = px.bar(
            x=[word[0] for word in top_pos_words],
            y=[word[1] for word in top_pos_words],
            labels={'x': 'Word', 'y': 'Frequency'},
            title='Top 10 Positive Words',
            color=[word[0] for word in top_pos_words],
            color_discrete_sequence=px.colors.qualitative.Pastel,
            width=900, 
            height=500
        )
        pos_words_div = pio.to_html(pos_words_fig, full_html=False)

        # Create negative words frequency plot
        neg_words_fig = px.bar(
            x=[word[0] for word in top_neg_words],
            y=[word[1] for word in top_neg_words],
            labels={'x': 'Word', 'y': 'Frequency'},
            title='Top 10 Negative Words',
            color=[word[0] for word in top_neg_words],
            color_discrete_sequence=px.colors.qualitative.Pastel,
            width=900, 
            height=500
        )
        neg_words_div = pio.to_html(neg_words_fig, full_html=False)

        # Calculate text statistics
        def calculate_text_stats(comments, sentiments):
            # Basic stats
            total_comments = len(comments)
            avg_length = round(sum(len(comment) for comment in comments) / total_comments, 2) if total_comments > 0 else 0
            
            # Word frequency
            all_words = ' '.join(comments).lower().split()
            filtered_words = [word for word in all_words if word.isalpha() and word not in stop_words]
            word_freq = Counter(filtered_words).most_common(10)
            
            # Readability scores
            readability_scores = []
            for comment in comments:
                if len(comment.split()) > 5:
                    readability_scores.append(textstat.flesch_reading_ease(comment))
            avg_readability = round(sum(readability_scores) / len(readability_scores), 2) if readability_scores else 0
            
            # Emoji and link counts
            emoji_count = sum(emoji.emoji_count(comment) for comment in comments)
            link_count = sum(bool(re.search(r"http[s]?://\S+", comment)) for comment in comments)
            
            # Sentiment distribution
            sentiment_counts = {
                'Positive': sentiments.count("Positive"),
                'Negative': sentiments.count("Negative"),
                'Neutral': sentiments.count("Neutral")
            }
            
            return {
                'total_comments': total_comments,
                'avg_length': avg_length,
                'top_words': word_freq,
                'avg_readability': avg_readability,
                'emoji_count': emoji_count,
                'link_count': link_count,
                'sentiment_distribution': sentiment_counts
            }

        text_stats = calculate_text_stats(relevant_comments, sentiments)

        # Create visualizations
        df = pd.DataFrame({'Sentiment': sentiments})
        sentiment_counts = df['Sentiment'].value_counts().reset_index()
        sentiment_counts.columns = ['Sentiment', 'Count']

        bar_fig = px.bar(sentiment_counts, x='Sentiment', y='Count', color='Sentiment', 
                         title='Sentiment Distribution', width=900, height=500)
        bar_div = pio.to_html(bar_fig, full_html=False)

        pie_fig = px.pie(df, names='Sentiment', title='Sentiment Proportion', 
                         hole=0.4, width=900, height=500)
        pie_div = pio.to_html(pie_fig, full_html=False)

        # Word frequency plot
        word_freq_fig = px.bar(
            x=[word[0] for word in text_stats['top_words']],
            y=[word[1] for word in text_stats['top_words']],
            labels={'x': 'Word', 'y': 'Frequency'},
            title='Top 10 Most Frequent Words (excluding stopwords)',
            # width=980, height=500
        )
        word_freq_div = pio.to_html(word_freq_fig, full_html=False)

        # Generate word clouds
        generate_wordcloud(pos, 'pos_wc.png')
        generate_wordcloud(neg, 'neg_wc.png')
        generate_wordcloud(neu, 'neu_wc.png')

        # Render template with all data
        rendered_html = render_template('result.html',
                               video_title=video_title,
                               video_views=video_views,
                               video_likes=video_likes,
                               video_comments=video_comments,
                               published_date=published_date,
                               channel_title=channel_title,
                               channel_subs=channel_subs,
                               total=len(polarity), 
                               pos=len(pos), 
                               neg=len(neg), 
                               neu=len(neu),
                               avg=avg, 
                               bar_plot=bar_div, 
                               pie_plot=pie_div,
                               pos_wc='static/pos_wc.png',
                               neg_wc='static/neg_wc.png',
                               neu_wc='static/neu_wc.png',
                               text_stats=text_stats,
                               word_freq_plot=word_freq_div,
                               pos_words_plot=pos_words_div,
                               neg_words_plot=neg_words_div)

        # Save full report
        with open("static/full_report.html", "w", encoding='utf-8') as f:
            f.write(rendered_html)

        return rendered_html
        
    except Exception as e:
        return f"Error analyzing video: {str(e)}"

@app.route('/download')
def download():
    try:
        return send_file('ytcomments.txt', as_attachment=True)
    except Exception as e:
        return f"Error downloading comments file: {e}"

@app.route('/download_full_report')
def download_full_report():
    try:
        return send_file('static/full_report.html', as_attachment=True)
    except Exception as e:
        return f"Error downloading full report: {e}"

@app.route('/send-email', methods=['POST'])
def send_email():
    try:
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        
        subject = 'Contact Form Submission from ' + name
        body = 'Name: ' + name + '\nEmail: ' + email + '\nMessage: ' + message

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login('markdummy4242@gmail.com', 'lhvm mafu pziv aqfn')
        server.sendmail('markdummy4242@gmail.com', 'ganeshusharma301@gmail.com', subject + '\n\n' + body)
        server.quit()

        return render_template('thank_you.html')
    except Exception as e:
        return f"Error sending email: {e}"

@app.route('/download_video/<video_id>')
def download_video(video_id):
    try:
        yt_url = f"https://www.youtube.com/watch?v={video_id}"
        yt = YouTube(yt_url)
        stream = yt.streams.get_highest_resolution()
        file_path = stream.download(output_path="static", filename=f"{video_id}.mp4")
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return f"Error downloading video: {e}"

if __name__ == '__main__':
    app.run(debug=True,port=5501)
