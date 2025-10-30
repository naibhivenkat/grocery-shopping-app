package com.example.groceryshoppingapp.network

import android.content.Context
import android.util.Log
import com.example.groceryshoppingapp.utils.SessionManager
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

object ApiClient {

    // private const val BASE_URL = "https://grocery-shopping-app-yyqx.onrender.com/"
    private const val BASE_URL = "https://grocery-backend-956424262985.asia-south1.run.app/"
    fun getRetrofit(context: Context): Retrofit {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }

        val client = OkHttpClient.Builder()
            .addInterceptor { chain ->
                val original: Request = chain.request()
                val builder = original.newBuilder()

                // ✅ Inject JWT automatically
                val token = SessionManager.getAuthToken(context)
                if (!token.isNullOrEmpty()) {
                    builder.addHeader("Authorization", "Bearer $token")


                }
                Log.d("RetrofitHeader", "Authorization header: ${builder.build().header("Authorization")}")

                chain.proceed(builder.build())
            }
            .addInterceptor(logging)
            .build()

        return Retrofit.Builder()
            .baseUrl(BASE_URL)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
    }

    fun getApiService(context: Context): ApiService =
        getRetrofit(context).create(ApiService::class.java)
}